from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlmodel import Session, select

from .db import (Equipment, EquipmentProgress, Inventory, InventoryTransaction,
                 Item, Recipe, Relic, RelicReward, RunSessionRecord, now)


def collection(session: Session) -> list[dict]:
    result = []
    items = {item.id: item for item in session.exec(select(Item)).all()}
    progress_rows = {row.equipment_id: row for row in session.exec(select(EquipmentProgress)).all()}
    owned = {row.item_id: row.quantity for row in session.exec(select(Inventory)).all()}
    recipes_by_equipment: dict[str, list[Recipe]] = {}
    for recipe in session.exec(select(Recipe)).all():
        recipes_by_equipment.setdefault(recipe.equipment_id, []).append(recipe)
    equipment_rows = session.exec(select(Equipment).order_by(Equipment.id)).all()
    for equipment in equipment_rows:
        item = items.get(equipment.id)
        progress = progress_rows.get(equipment.id)
        if not item or not progress:
            continue
        parts = []
        for recipe in recipes_by_equipment.get(equipment.id, []):
            component = items.get(recipe.component_id)
            if component:
                parts.append({"id":component.id,"name":component.name,"required":recipe.quantity,
                    "owned":owned.get(component.id, 0),"ducats":component.ducats,
                    "market_median":component.market_median,"availability":component.availability})
        parts.sort(key=lambda part: part["name"])
        ready = all(part["owned"] >= part["required"] for part in parts)
        result.append({"id":item.id,"name":item.name,"availability":item.availability,
            "type":item.kind,
            "founder_exclusive":equipment.founder_exclusive,
            "mastered":progress.mastered,
            "parts":parts,"ready":ready,
            "missing_count":sum(max(0,p["required"]-p["owned"]) for p in parts),
            "surplus_sets":min((p["owned"]//p["required"] for p in parts),default=0)})
    return sorted(result, key=lambda row: row["name"])


def build_equipment(session: Session, equipment_id: str) -> dict:
    if not session.get(Equipment, equipment_id): raise HTTPException(404, "Equipment not found")
    recipes = session.exec(select(Recipe).where(Recipe.equipment_id == equipment_id)).all()
    inventories = {recipe.component_id: session.get(Inventory, recipe.component_id) for recipe in recipes}
    if not recipes or any(not inventories[r.component_id] or inventories[r.component_id].quantity < r.quantity for r in recipes):
        raise HTTPException(409, "Not enough parts to build this set")
    for recipe in recipes:
        inventory = inventories[recipe.component_id]
        inventory.quantity -= recipe.quantity; inventory.verified_at = now()
    return {"equipment_id": equipment_id, "built": True}


def session_view(session: Session, session_id: str) -> dict:
    run = session.get(RunSessionRecord, session_id)
    if not run:
        raise HTTPException(404, "Run session not found")
    columns=[]
    for relic_id in json.loads(run.slots_json):
        relic=session.get(Relic,relic_id)
        if not relic: continue
        rewards=[]
        links=session.exec(select(RelicReward).where(RelicReward.relic_id==relic_id)).all()
        for link in links:
            item=session.get(Item,link.item_id)
            if not item: continue
            inventory=session.get(Inventory,item.id)
            recipes=session.exec(select(Recipe).where(Recipe.component_id==item.id)).all()
            required=sum(recipe.quantity for recipe in recipes)
            progress=[session.get(EquipmentProgress,recipe.equipment_id) for recipe in recipes]
            equipment_ids={recipe.equipment_id for recipe in recipes}
            ready=[]
            for equipment_id in equipment_ids:
                requirements=session.exec(select(Recipe).where(Recipe.equipment_id==equipment_id)).all()
                ready.append(bool(requirements) and all(
                    (owned:=session.get(Inventory,requirement.component_id)) is not None
                    and owned.quantity>=requirement.quantity for requirement in requirements))
            rewards.append({"id":item.id,"name":item.name,"rarity":link.rarity,"ducats":item.ducats,
                "market_median":item.market_median,"market_window":item.market_window,
                "availability":item.availability,"owned":inventory.quantity if inventory else 0,
                "required":required,
                "part_owned":required>0 and inventory is not None and inventory.quantity>=required,
                "mastered":bool(progress) and all(row and row.mastered for row in progress),
                "set_complete":any(ready)})
        rarity_order={"rare":0,"uncommon":1,"common":2}
        rewards.sort(key=lambda reward:(rarity_order.get(reward["rarity"],3),reward["name"]))
        columns.append({**relic.model_dump(),"rewards":rewards})
    return {"id":run.id,"state":run.state,"chosen_item_id":run.chosen_item_id,"columns":columns}


def create_session(session: Session, relic_ids: list[str]) -> dict:
    unique=set(relic_ids)
    found=session.exec(select(Relic.id).where(Relic.id.in_(unique))).all()
    if len(found)!=len(unique): raise HTTPException(422,"Unknown relic")
    run=RunSessionRecord(id=str(uuid.uuid4()),slots_json=json.dumps(relic_ids))
    session.add(run); session.flush()
    return session_view(session,run.id)


def confirm_reward(session: Session, session_id: str, item_id: str, key: str) -> dict:
    existing=session.exec(select(InventoryTransaction).where(InventoryTransaction.idempotency_key==key)).first()
    if existing: return {"transaction_id":existing.id,"duplicate":True}
    run=session.get(RunSessionRecord,session_id)
    if not run or run.state!="open": raise HTTPException(409,"Run is not open")
    slots=json.loads(run.slots_json)
    valid=session.exec(select(RelicReward).where(RelicReward.item_id==item_id,RelicReward.relic_id.in_(slots))).first()
    if not valid: raise HTTPException(422,"Reward is not in this squad rotation")
    inventory=session.get(Inventory,item_id)
    if inventory: inventory.quantity+=1; inventory.verified_at=now()
    else: session.add(Inventory(item_id=item_id,quantity=1))
    transaction=InventoryTransaction(id=str(uuid.uuid4()),session_id=session_id,item_id=item_id,idempotency_key=key)
    session.add(transaction); run.chosen_item_id=item_id; run.state="confirmed"; session.flush()
    return {"transaction_id":transaction.id,"duplicate":False}


def undo(session: Session, transaction_id: str) -> None:
    transaction=session.get(InventoryTransaction,transaction_id)
    if not transaction: raise HTTPException(404,"Transaction not found")
    if transaction.undone: return
    inventory=session.get(Inventory,transaction.item_id)
    if not inventory or inventory.quantity<1: raise HTTPException(409,"Inventory changed; cannot safely undo")
    inventory.quantity-=1; inventory.verified_at=now(); transaction.undone=True
    run=session.get(RunSessionRecord,transaction.session_id)
    if run: run.state="open"; run.chosen_item_id=None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
