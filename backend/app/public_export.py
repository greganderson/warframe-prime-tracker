from __future__ import annotations

import hashlib
import json
import lzma
import re
import time
from datetime import datetime, timezone

import httpx
from sqlmodel import select

from .db import AppMetadata, Inventory, Item, Relic, RelicReward, session_scope

INDEX_URLS = ["https://origin.warframe.com/PublicExport/index_en.txt.lzma",
              "https://content.warframe.com/PublicExport/index_en.txt.lzma"]
MANIFEST_BASES = ["https://content.warframe.com/PublicExport/Manifest/",
                  "http://content.warframe.com/PublicExport/Manifest/"]
RELIC_NAME = re.compile(r"^(Lith|Meso|Neo|Axi) ([A-Z]+\d+) Relic$")


class CatalogRefreshError(RuntimeError):
    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(message)


def _download(urls: list[str], stage: str) -> bytes:
    errors=[]
    for attempt in range(3):
        for url in urls:
            try:
                with httpx.Client(follow_redirects=True,timeout=httpx.Timeout(45,connect=15),
                                  headers={"User-Agent":"warframe-prime-tracker/1.0","Accept":"*/*"}) as client:
                    response=client.get(url); response.raise_for_status()
                    if not response.content: raise ValueError("empty response")
                    return response.content
            except (httpx.HTTPError,ValueError) as error:
                errors.append(f"{url}: {error}")
        if attempt<2: time.sleep(0.5*(attempt+1))
    raise CatalogRefreshError(stage,"; ".join(errors[-4:]))


def decode_export_index(content: bytes) -> str:
    """Decode Public Export indexes across CDN/client content encodings.

    Some CDN edges label the LZMA response in a way that HTTP clients decode
    automatically. In that case ``response.content`` is already the plaintext
    index even though the URL still ends in ``.lzma``.
    """
    candidate = content.lstrip(b"\xef\xbb\xbf\r\n\t ")
    if candidate.startswith(b"Export"):
        try:
            return candidate.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CatalogRefreshError("index_decode", f"plaintext index was not UTF-8: {error}") from error
    errors=[]
    try:
        decoded = lzma.decompress(content).decode("utf-8-sig")
    except (lzma.LZMAError, UnicodeDecodeError) as error:
        errors.append(str(error))
        try:
            decoded = _decode_legacy_lzma_raw(content).decode("utf-8-sig")
        except (lzma.LZMAError, UnicodeDecodeError, ValueError) as fallback_error:
            errors.append(str(fallback_error))
            prefix = content[:13].hex() or "empty"
            raise CatalogRefreshError("index_decode", f"unrecognized index encoding ({len(content)} bytes, prefix {prefix}): {'; '.join(errors)}") from fallback_error
    if not decoded.lstrip().startswith("Export"):
        raise CatalogRefreshError("index_decode", "decoded index did not begin with an Export entry")
    return decoded


def _decode_legacy_lzma_raw(content: bytes) -> bytes:
    """Decode an LZMA-alone stream without relying on FORMAT_ALONE.

    The official index uses the 13-byte legacy header. Some Windows liblzma
    builds reject its declared-size variant in FORMAT_AUTO/FORMAT_ALONE even
    though the raw LZMA1 payload is valid.
    """
    if len(content) <= 13:
        raise ValueError("legacy LZMA stream is shorter than its header")
    properties = content[0]
    if properties >= 9 * 5 * 5:
        raise ValueError(f"invalid LZMA properties byte {properties}")
    lc = properties % 9
    remainder = properties // 9
    lp = remainder % 5
    pb = remainder // 5
    dictionary_size = int.from_bytes(content[1:5], "little")
    if dictionary_size <= 0 or dictionary_size > 1 << 30:
        raise ValueError(f"invalid LZMA dictionary size {dictionary_size}")
    decoded = lzma.decompress(content[13:], format=lzma.FORMAT_RAW, filters=[{
        "id": lzma.FILTER_LZMA1, "dict_size": dictionary_size,
        "lc": lc, "lp": lp, "pb": pb,
    }])
    expected_size = int.from_bytes(content[5:13], "little")
    if expected_size != 0xFFFFFFFFFFFFFFFF and len(decoded) != expected_size:
        raise ValueError(f"legacy LZMA size mismatch: expected {expected_size}, decoded {len(decoded)}")
    return decoded


def fetch_relic_manifest() -> dict:
    index=decode_export_index(_download(INDEX_URLS,"index_download"))
    filename=next((line for line in index.splitlines() if line.startswith("ExportRelicArcane_en.json!")),None)
    if not filename: raise CatalogRefreshError("index_parse","relic manifest filename was missing")
    try: payload=json.loads(_download([base+filename for base in MANIFEST_BASES],"manifest_download"))
    except CatalogRefreshError: raise
    except json.JSONDecodeError as error: raise CatalogRefreshError("manifest_decode",str(error)) from error
    if not isinstance(payload.get("ExportRelicArcane"),list):
        raise CatalogRefreshError("manifest_validate","ExportRelicArcane list was missing")
    return payload


def _reward_id(unique_name:str)->str: return "export-"+hashlib.sha1(unique_name.encode()).hexdigest()[:20]


def _reward_name(unique_name:str)->str:
    leaf=unique_name.rsplit("/",1)[-1]
    if leaf=="FormaBlueprint": return "Forma Blueprint"
    name=re.sub(r"(?<=[a-z0-9])(?=[A-Z])"," ",leaf)
    return re.sub(r"\s+"," ",re.sub(r"Prime(?=[A-Z])","Prime ",name).replace("Blueprint"," Blueprint")).strip()


def normalize_relics(payload:dict)->list[dict]:
    normalized={}
    for entry in payload["ExportRelicArcane"]:
        match=RELIC_NAME.match(entry.get("name","")); rewards=entry.get("relicRewards")
        if not match or not isinstance(rewards,list) or len(rewards)<6: continue
        era,code=match.groups(); relic_id=f"{era.lower()}-{code.lower()}"
        normalized.setdefault(relic_id,{"id":relic_id,"era":era,"code":code,"rewards":rewards})
    if len(normalized)<100: raise CatalogRefreshError("manifest_validate",f"only {len(normalized)} valid relics")
    return list(normalized.values())


def _set_metadata(session,key:str,value:str)->None:
    record=session.get(AppMetadata,key)
    if record: record.value=value
    else: session.add(AppMetadata(key=key,value=value))


def refresh_relic_catalog(payload:dict|None=None)->int:
    try:
        relics=normalize_relics(payload or fetch_relic_manifest())
        with session_scope() as session:
            for data in relics:
                relic=session.get(Relic,data["id"])
                if relic: relic.era=data["era"]; relic.code=data["code"]
                else: relic=Relic(id=data["id"],era=data["era"],code=data["code"]); session.add(relic)
                for old in session.exec(select(RelicReward).where(RelicReward.relic_id==data["id"])).all(): session.delete(old)
                session.flush()
                linked=set()
                for reward in data["rewards"]:
                    unique_name=reward["rewardName"]; display_name=_reward_name(unique_name)
                    item=session.exec(select(Item).where(Item.name==display_name)).first()
                    if not item:
                        item=session.get(Item,_reward_id(unique_name))
                    if not item:
                        item=Item(id=_reward_id(unique_name),name=display_name,kind="component"); session.add(item); session.flush()
                    if not session.get(Inventory,item.id): session.add(Inventory(item_id=item.id))
                    if item.id in linked: continue
                    rarity=str(reward.get("rarity","COMMON")).lower()
                    session.add(RelicReward(relic_id=relic.id,item_id=item.id,rarity=rarity if rarity in {"common","uncommon","rare"} else "common")); linked.add(item.id)
            _set_metadata(session,"relic_catalog_refreshed_at",datetime.now(timezone.utc).isoformat())
            _set_metadata(session,"relic_catalog_count",str(len(relics)))
            _set_metadata(session,"relic_catalog_error","")
        return len(relics)
    except CatalogRefreshError: raise
    except Exception as error: raise CatalogRefreshError("database_import",f"{type(error).__name__}: {error}") from error
