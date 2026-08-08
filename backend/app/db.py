from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(os.getenv("TRACKER_DB", Path(__file__).parents[2] / "data" / "tracker.db"))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
  ducats INTEGER NOT NULL DEFAULT 0, market_median REAL, market_window TEXT,
  availability TEXT NOT NULL DEFAULT 'unknown', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS equipment (
  id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  founder_exclusive INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recipes (
  equipment_id TEXT NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
  component_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  quantity INTEGER NOT NULL CHECK(quantity > 0),
  PRIMARY KEY(equipment_id, component_id)
);
CREATE TABLE IF NOT EXISTS relics (
  id TEXT PRIMARY KEY, era TEXT NOT NULL, code TEXT NOT NULL,
  availability TEXT NOT NULL DEFAULT 'unknown', UNIQUE(era, code)
);
CREATE TABLE IF NOT EXISTS relic_rewards (
  relic_id TEXT NOT NULL REFERENCES relics(id) ON DELETE CASCADE,
  item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  rarity TEXT NOT NULL CHECK(rarity IN ('common','uncommon','rare')),
  PRIMARY KEY(relic_id,item_id)
);
CREATE TABLE IF NOT EXISTS inventory (
  item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0), verified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS equipment_progress (
  equipment_id TEXT PRIMARY KEY REFERENCES equipment(id) ON DELETE CASCADE,
  owned INTEGER NOT NULL DEFAULT 0, mastered INTEGER NOT NULL DEFAULT 0,
  favorite INTEGER NOT NULL DEFAULT 0, target INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_sessions (
  id TEXT PRIMARY KEY, slots_json TEXT NOT NULL DEFAULT '[]',
  chosen_item_id TEXT, state TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES run_sessions(id),
  item_id TEXT NOT NULL REFERENCES items(id),
  idempotency_key TEXT NOT NULL UNIQUE, undone INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize() -> None:
    with connect() as db:
        db.executescript(SCHEMA)
        # Relic ownership was removed in schema version 2. Existing databases may
        # retain legacy columns, but the quantity table is no longer used.
        db.execute("DROP TABLE IF EXISTS relic_inventory")
        db.execute("INSERT INTO metadata(key,value) VALUES('schema_version','2') ON CONFLICT(key) DO UPDATE SET value='2'")
        seed(db)


def seed(db: sqlite3.Connection) -> None:
    if db.execute("SELECT COUNT(*) FROM items").fetchone()[0]:
        return
    items = [
        ("boar-prime", "Boar Prime", "equipment", 0, None, None, "vaulted"),
        ("boar-prime-blueprint", "Boar Prime Blueprint", "component", 25, 5.0, "48h", "vaulted"),
        ("boar-prime-barrel", "Boar Prime Barrel", "component", 45, 8.0, "48h", "vaulted"),
        ("boar-prime-receiver", "Boar Prime Receiver", "component", 45, 7.0, "48h", "vaulted"),
        ("boar-prime-stock", "Boar Prime Stock", "component", 25, 4.0, "48h", "vaulted"),
        ("forma-blueprint", "Forma Blueprint", "special", 0, None, None, "farmable"),
    ]
    db.executemany("INSERT INTO items(id,name,kind,ducats,market_median,market_window,availability) VALUES(?,?,?,?,?,?,?)", items)
    db.execute("INSERT INTO equipment(id) VALUES('boar-prime')")
    db.executemany("INSERT INTO recipes VALUES(?,?,?)", [
        ("boar-prime", "boar-prime-blueprint", 1), ("boar-prime", "boar-prime-barrel", 1),
        ("boar-prime", "boar-prime-receiver", 1), ("boar-prime", "boar-prime-stock", 1),
    ])
    db.executemany("INSERT INTO relics(id,era,code,availability) VALUES(?,?,?,?)", [
        ("lith-b4", "Lith", "B4", "vaulted"), ("meso-b1", "Meso", "B1", "vaulted")
    ])
    db.executemany("INSERT INTO relic_rewards VALUES(?,?,?)", [
        ("lith-b4", "boar-prime-barrel", "rare"), ("lith-b4", "boar-prime-blueprint", "common"),
        ("lith-b4", "forma-blueprint", "common"), ("meso-b1", "boar-prime-receiver", "uncommon"),
        ("meso-b1", "boar-prime-stock", "common"), ("meso-b1", "forma-blueprint", "common")
    ])
    db.executemany("INSERT INTO inventory(item_id,quantity) VALUES(?,?)", [(x[0], 0) for x in items if x[2] != "equipment"])
    db.execute("INSERT INTO equipment_progress(equipment_id) VALUES('boar-prime')")
    db.execute("INSERT INTO metadata VALUES('catalog_notice', ?)", (json.dumps("Demonstration catalog; run a catalog sync before relying on availability."),))
