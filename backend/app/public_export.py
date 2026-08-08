from __future__ import annotations

import hashlib
import json
import lzma
import re
import time
from datetime import datetime, timezone

import httpx
from sqlmodel import select

from .db import (AppMetadata, Equipment, EquipmentProgress, Inventory, Item,
                 Recipe, Relic, RelicReward, session_scope)

INDEX_URLS = ["https://origin.warframe.com/PublicExport/index_en.txt.lzma",
              "https://content.warframe.com/PublicExport/index_en.txt.lzma"]
MANIFEST_BASES = ["https://content.warframe.com/PublicExport/Manifest/",
                  "http://content.warframe.com/PublicExport/Manifest/"]
RELIC_NAME = re.compile(r"^(Lith|Meso|Neo|Axi) ([A-Z]+\d+) Relic$")
CATALOG_EXPORTS = {
    "relics": "ExportRelicArcane_en.json!",
    "recipes": "ExportRecipes_en.json!",
    "resources": "ExportResources_en.json!",
    "warframes": "ExportWarframes_en.json!",
    "weapons": "ExportWeapons_en.json!",
}


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


def fetch_catalog_manifests() -> dict[str, dict]:
    index=decode_export_index(_download(INDEX_URLS,"index_download"))
    manifests={}
    for key,prefix in CATALOG_EXPORTS.items():
        filename=next((line for line in index.splitlines() if line.startswith(prefix)),None)
        if not filename: raise CatalogRefreshError("index_parse",f"{key} manifest filename was missing")
        try: manifests[key]=json.loads(_download([base+filename for base in MANIFEST_BASES],f"{key}_download"))
        except CatalogRefreshError: raise
        except json.JSONDecodeError as error: raise CatalogRefreshError(f"{key}_decode",str(error)) from error
    return manifests


def fetch_relic_manifest() -> dict:
    return fetch_catalog_manifests()["relics"]


def _reward_id(unique_name:str)->str: return "export-"+hashlib.sha1(unique_name.encode()).hexdigest()[:20]


def _reward_name(unique_name:str)->str:
    leaf=unique_name.rsplit("/",1)[-1]
    if leaf=="FormaBlueprint": return "Forma Blueprint"
    name=re.sub(r"(?<=[a-z0-9])(?=[A-Z])"," ",leaf)
    name=re.sub(r"\s+"," ",re.sub(r"Prime(?=[A-Z])","Prime ",name).replace("Blueprint"," Blueprint")).strip()
    return name.replace(" Helmet Blueprint", " Neuroptics Blueprint")


def _store_path(unique_name:str)->str:
    return unique_name.replace("/Lotus/", "/Lotus/StoreItems/", 1) if unique_name.startswith("/Lotus/") else unique_name


def _slug(name:str)->str:
    return re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")


def normalize_equipment(manifests:dict[str,dict])->list[dict]:
    recipes=manifests["recipes"].get("ExportRecipes",[])
    resources={row.get("uniqueName"):row for row in manifests["resources"].get("ExportResources",[])}
    recipe_by_result={row.get("resultType"):row for row in recipes if row.get("resultType")}
    sources=[("warframe",manifests["warframes"].get("ExportWarframes",[])),
             ("weapon",manifests["weapons"].get("ExportWeapons",[]))]
    equipment_index={row.get("uniqueName"):(kind,row) for kind,rows in sources for row in rows
                     if row.get("uniqueName") and " Prime" in row.get("name","")}
    def recipe_parts(equipment_row:dict,multiplier:int=1,stack:frozenset[str]=frozenset())->list[dict]:
        unique_name=equipment_row["uniqueName"]
        if unique_name in stack: return []
        main=recipe_by_result.get(unique_name)
        if not main: return []
        name=equipment_row["name"]
        parts=[{"source":main["uniqueName"],"name":f"{name} Blueprint","quantity":multiplier,
                "ducats":main.get("primeSellingPrice",0)}]
        for ingredient in main.get("ingredients",[]):
            source=ingredient.get("ItemType",""); quantity=int(ingredient.get("ItemCount",1))*multiplier
            if source in equipment_index:
                parts.extend(recipe_parts(equipment_index[source][1],quantity,stack|{unique_name}))
                continue
            component_recipe=recipe_by_result.get(source)
            if component_recipe and "Prime" in component_recipe.get("uniqueName",""):
                part_source=component_recipe["uniqueName"]
                parts.append({"source":part_source,"name":_reward_name(_store_path(part_source)),
                              "quantity":quantity,"ducats":component_recipe.get("primeSellingPrice",0)})
            elif source in resources and " Prime " in f" {resources[source].get('name','')} ":
                resource=resources[source]
                parts.append({"source":source,"name":resource["name"],"quantity":quantity,
                              "ducats":resource.get("primeSellingPrice",0)})
        combined={}
        for part in parts:
            if part["source"] in combined: combined[part["source"]]["quantity"]+=part["quantity"]
            else: combined[part["source"]]=part.copy()
        return list(combined.values())
    equipment=[]
    for kind,rows in sources:
        for row in rows:
            name=row.get("name","")
            if " Prime" not in name or not row.get("uniqueName"): continue
            main=recipe_by_result.get(row["uniqueName"])
            if not main: continue
            parts=recipe_parts(row)
            if len(parts)>=2:
                equipment.append({"id":_slug(name),"name":name,"kind":kind,"parts":parts,
                                  "founder_exclusive":name in {"Excalibur Prime","Lato Prime","Skana Prime"}})
    if len(equipment)<100: raise CatalogRefreshError("equipment_validate",f"only {len(equipment)} Prime equipment recipes")
    return equipment


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


def _item_for_part(session,source:str,name:str,ducats:int)->Item:
    item=session.exec(select(Item).where(Item.name==name)).first()
    if not item: item=session.get(Item,_reward_id(_store_path(source)))
    if not item:
        item=Item(id=_reward_id(_store_path(source)),name=name,kind="component",ducats=ducats)
        session.add(item); session.flush()
    else:
        item.name=name
        if ducats and not item.ducats: item.ducats=ducats
    if not session.get(Inventory,item.id): session.add(Inventory(item_id=item.id))
    return item


def import_equipment_catalog(session,equipment_rows:list[dict])->None:
    for data in equipment_rows:
        item=session.exec(select(Item).where(Item.name==data["name"])).first()
        if not item: item=Item(id=data["id"],name=data["name"],kind=data["kind"]); session.add(item); session.flush()
        else: item.kind=data["kind"]
        equipment=session.get(Equipment,item.id)
        if not equipment:
            equipment=Equipment(id=item.id,founder_exclusive=data["founder_exclusive"]); session.add(equipment); session.flush()
        else: equipment.founder_exclusive=data["founder_exclusive"]
        if not session.get(EquipmentProgress,item.id): session.add(EquipmentProgress(equipment_id=item.id))
        for old in session.exec(select(Recipe).where(Recipe.equipment_id==item.id)).all(): session.delete(old)
        session.flush()
        for part in data["parts"]:
            component=_item_for_part(session,part["source"],part["name"],part["ducats"])
            session.add(Recipe(equipment_id=item.id,component_id=component.id,quantity=part["quantity"]))


def refresh_relic_catalog(payload:dict|None=None, manifests:dict[str,dict]|None=None)->int:
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
                    else:
                        item.name=display_name
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


def refresh_full_catalog(manifests:dict[str,dict]|None=None)->dict:
    bundle=manifests or fetch_catalog_manifests()
    equipment=normalize_equipment(bundle)
    relic_count=refresh_relic_catalog(bundle["relics"])
    try:
        with session_scope() as session:
            import_equipment_catalog(session,equipment)
            _set_metadata(session,"equipment_catalog_count",str(len(equipment)))
            _set_metadata(session,"equipment_catalog_refreshed_at",datetime.now(timezone.utc).isoformat())
        return {"relics":relic_count,"equipment":len(equipment)}
    except Exception as error:
        raise CatalogRefreshError("equipment_import",f"{type(error).__name__}: {error}") from error
