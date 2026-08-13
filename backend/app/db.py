from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, create_engine, select

DB_PATH = Path(os.getenv("TRACKER_DB", Path(__file__).parents[2] / "data" / "tracker.db"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Item(SQLModel, table=True):
    __tablename__ = "items"
    id: str = Field(primary_key=True)
    name: str = Field(unique=True, index=True)
    kind: str
    ducats: int = 0
    market_median: float | None = None
    market_window: str | None = None
    availability: str = "unknown"
    updated_at: str = Field(default_factory=now)


class Equipment(SQLModel, table=True):
    __tablename__ = "equipment"
    id: str = Field(primary_key=True, foreign_key="items.id")
    founder_exclusive: bool = False


class Recipe(SQLModel, table=True):
    __tablename__ = "recipes"
    equipment_id: str = Field(primary_key=True, foreign_key="equipment.id")
    component_id: str = Field(primary_key=True, foreign_key="items.id")
    quantity: int


class Relic(SQLModel, table=True):
    __tablename__ = "relics"
    id: str = Field(primary_key=True)
    era: str = Field(index=True)
    code: str = Field(index=True)
    availability: str = "unknown"


class RelicReward(SQLModel, table=True):
    __tablename__ = "relic_rewards"
    relic_id: str = Field(primary_key=True, foreign_key="relics.id")
    item_id: str = Field(primary_key=True, foreign_key="items.id")
    rarity: str


class Inventory(SQLModel, table=True):
    __tablename__ = "inventory"
    item_id: str = Field(primary_key=True, foreign_key="items.id")
    quantity: int = 0
    verified_at: str = Field(default_factory=now)


class EquipmentProgress(SQLModel, table=True):
    __tablename__ = "equipment_progress"
    equipment_id: str = Field(primary_key=True, foreign_key="equipment.id")
    mastered: bool = False


class RunSessionRecord(SQLModel, table=True):
    __tablename__ = "run_sessions"
    id: str = Field(primary_key=True)
    slots_json: str = "[]"
    chosen_item_id: str | None = None
    state: str = "open"
    created_at: str = Field(default_factory=now)


class InventoryTransaction(SQLModel, table=True):
    __tablename__ = "transactions"
    id: str = Field(primary_key=True)
    session_id: str = Field(foreign_key="run_sessions.id", index=True)
    item_id: str = Field(foreign_key="items.id")
    idempotency_key: str = Field(unique=True, index=True)
    undone: bool = False
    created_at: str = Field(default_factory=now)


class AppMetadata(SQLModel, table=True):
    __tablename__ = "metadata"
    key: str = Field(primary_key=True)
    value: str


MODELS = [Item, Equipment, Recipe, Relic, RelicReward, Inventory,
          EquipmentProgress, RunSessionRecord, InventoryTransaction, AppMetadata]
MODEL_BY_TABLE = {model.__tablename__: model for model in MODELS}


def _make_engine():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 10})
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
    return engine


engine = _make_engine()


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def initialize() -> None:
    SQLModel.metadata.create_all(engine)
    with session_scope() as session:
        metadata = session.get(AppMetadata, "schema_version")
        if metadata:
            metadata.value = "5"
        else:
            session.add(AppMetadata(key="schema_version", value="5"))
        seed(session)


def seed(session: Session) -> None:
    if session.exec(select(Item).limit(1)).first():
        return
    items = [
        Item(id="boar-prime", name="Boar Prime", kind="equipment", availability="vaulted"),
        Item(id="boar-prime-blueprint", name="Boar Prime Blueprint", kind="component", ducats=25, market_median=5, market_window="48h", availability="vaulted"),
        Item(id="boar-prime-barrel", name="Boar Prime Barrel", kind="component", ducats=45, market_median=8, market_window="48h", availability="vaulted"),
        Item(id="boar-prime-receiver", name="Boar Prime Receiver", kind="component", ducats=45, market_median=7, market_window="48h", availability="vaulted"),
        Item(id="boar-prime-stock", name="Boar Prime Stock", kind="component", ducats=25, market_median=4, market_window="48h", availability="vaulted"),
        Item(id="forma-blueprint", name="Forma Blueprint", kind="special", availability="farmable"),
    ]
    session.add_all(items)
    session.flush()
    session.add(Equipment(id="boar-prime"))
    session.flush()
    session.add_all([Recipe(equipment_id="boar-prime", component_id=item_id, quantity=1) for item_id in
                     ["boar-prime-blueprint", "boar-prime-barrel", "boar-prime-receiver", "boar-prime-stock"]])
    session.add_all([Relic(id="lith-b4", era="Lith", code="B4", availability="vaulted"),
                     Relic(id="meso-b1", era="Meso", code="B1", availability="vaulted")])
    session.flush()
    session.add_all([RelicReward(relic_id=a,item_id=b,rarity=c) for a,b,c in [
        ("lith-b4","boar-prime-barrel","rare"), ("lith-b4","boar-prime-blueprint","common"),
        ("lith-b4","forma-blueprint","common"), ("meso-b1","boar-prime-receiver","uncommon"),
        ("meso-b1","boar-prime-stock","common"), ("meso-b1","forma-blueprint","common")]])
    session.add_all([Inventory(item_id=item.id) for item in items if item.kind != "equipment"])
    session.add(EquipmentProgress(equipment_id="boar-prime"))
    session.add(AppMetadata(key="catalog_notice", value=json.dumps("Demonstration equipment catalog; relics refresh from Public Export.")))
