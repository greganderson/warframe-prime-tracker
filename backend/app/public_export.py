from __future__ import annotations

import hashlib
import json
import lzma
import re
import urllib.request
from datetime import datetime, timezone

from . import db as database

INDEX_URL = "https://origin.warframe.com/PublicExport/index_en.txt.lzma"
MANIFEST_BASE = "https://content.warframe.com/PublicExport/Manifest/"
RELIC_NAME = re.compile(r"^(Lith|Meso|Neo|Axi) ([A-Z]+\d+) Relic$")


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "warframe-prime-tracker/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch_relic_manifest() -> dict:
    index = lzma.decompress(_download(INDEX_URL)).decode("utf-8")
    filename = next((line for line in index.splitlines() if line.startswith("ExportRelicArcane_en.json!")), None)
    if not filename:
        raise ValueError("Official export index did not contain the relic manifest")
    payload = json.loads(_download(MANIFEST_BASE + filename))
    if not isinstance(payload.get("ExportRelicArcane"), list):
        raise ValueError("Official relic manifest has an unexpected format")
    return payload


def _reward_id(unique_name: str) -> str:
    return "export-" + hashlib.sha1(unique_name.encode()).hexdigest()[:20]


def _reward_name(unique_name: str) -> str:
    leaf = unique_name.rsplit("/", 1)[-1]
    known = {"FormaBlueprint": "Forma Blueprint"}
    if leaf in known:
        return known[leaf]
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", leaf)
    name = re.sub(r"Prime(?=[A-Z])", "Prime ", name)
    name = name.replace("Blueprint", " Blueprint").replace("  ", " ")
    return name.strip()


def normalize_relics(payload: dict) -> list[dict]:
    # Public Export contains one entry per refinement; Run mode deliberately
    # ignores refinement, so collapse the four identical names into one relic.
    normalized: dict[str, dict] = {}
    for entry in payload["ExportRelicArcane"]:
        match = RELIC_NAME.match(entry.get("name", ""))
        rewards = entry.get("relicRewards")
        if not match or not isinstance(rewards, list) or len(rewards) < 6:
            continue
        era, code = match.groups()
        relic_id = f"{era.lower()}-{code.lower()}"
        normalized.setdefault(relic_id, {"id": relic_id, "era": era, "code": code, "rewards": rewards})
    if len(normalized) < 100:
        raise ValueError(f"Refusing incomplete relic catalog ({len(normalized)} relics)")
    return list(normalized.values())


def refresh_relic_catalog(payload: dict | None = None) -> int:
    relics = normalize_relics(payload or fetch_relic_manifest())
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction() as db:
        for relic in relics:
            db.execute("""INSERT INTO relics(id,era,code,availability) VALUES(?,?,?,'unknown')
                ON CONFLICT(id) DO UPDATE SET era=excluded.era,code=excluded.code""", (relic["id"], relic["era"], relic["code"]))
            db.execute("DELETE FROM relic_rewards WHERE relic_id=?", (relic["id"],))
            for reward in relic["rewards"]:
                unique_name = reward["rewardName"]
                item_id = _reward_id(unique_name)
                display_name = _reward_name(unique_name)
                existing = db.execute("SELECT id FROM items WHERE name=?", (display_name,)).fetchone()
                if existing:
                    item_id = existing["id"]
                db.execute("""INSERT INTO items(id,name,kind,availability) VALUES(?,?,'component','unknown')
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name""", (item_id, display_name))
                db.execute("INSERT OR IGNORE INTO inventory(item_id,quantity) VALUES(?,0)", (item_id,))
                rarity = str(reward.get("rarity", "COMMON")).lower()
                if rarity not in {"common", "uncommon", "rare"}: rarity = "common"
                db.execute("INSERT OR IGNORE INTO relic_rewards(relic_id,item_id,rarity) VALUES(?,?,?)", (relic["id"], item_id, rarity))
        db.execute("INSERT INTO metadata(key,value) VALUES('relic_catalog_refreshed_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now,))
        db.execute("INSERT INTO metadata(key,value) VALUES('relic_catalog_count',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(len(relics)),))
    return len(relics)
