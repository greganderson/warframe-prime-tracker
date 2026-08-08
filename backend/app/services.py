from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException


def collection(db: sqlite3.Connection) -> list[dict]:
    equipment = db.execute("""
      SELECT i.id,i.name,i.availability,e.founder_exclusive,p.owned,p.mastered,p.favorite,p.target
      FROM equipment e JOIN items i ON i.id=e.id JOIN equipment_progress p ON p.equipment_id=e.id
      ORDER BY i.name
    """).fetchall()
    result = []
    for eq in equipment:
        parts = [dict(r) for r in db.execute("""
          SELECT i.id,i.name,r.quantity required,COALESCE(inv.quantity,0) owned,i.ducats,i.market_median,
                 i.availability
          FROM recipes r JOIN items i ON i.id=r.component_id
          LEFT JOIN inventory inv ON inv.item_id=i.id WHERE r.equipment_id=? ORDER BY i.name
        """, (eq["id"],))]
        ready = all(p["owned"] >= p["required"] for p in parts)
        missing = sum(max(0, p["required"] - p["owned"]) for p in parts)
        result.append({**dict(eq), "parts": parts, "ready": ready, "missing_count": missing,
                       "surplus_sets": min((p["owned"] // p["required"] for p in parts), default=0)})
    return result


def session_view(db: sqlite3.Connection, session_id: str) -> dict:
    session = db.execute("SELECT * FROM run_sessions WHERE id=?", (session_id,)).fetchone()
    if not session:
        raise HTTPException(404, "Run session not found")
    slots = json.loads(session["slots_json"])
    columns = []
    for relic_id in slots:
        relic = db.execute("SELECT r.*,COALESCE(ri.quantity,0) owned FROM relics r LEFT JOIN relic_inventory ri ON ri.relic_id=r.id WHERE r.id=?", (relic_id,)).fetchone()
        rewards = [dict(x) for x in db.execute("""
          SELECT i.id,i.name,rr.rarity,i.ducats,i.market_median,i.market_window,i.availability,
                 COALESCE(inv.quantity,0) owned,
                 COALESCE((SELECT SUM(quantity) FROM recipes WHERE component_id=i.id),0) required
          FROM relic_rewards rr JOIN items i ON i.id=rr.item_id
          LEFT JOIN inventory inv ON inv.item_id=i.id WHERE rr.relic_id=?
          ORDER BY CASE rr.rarity WHEN 'rare' THEN 1 WHEN 'uncommon' THEN 2 ELSE 3 END,i.name
        """, (relic_id,))]
        columns.append({**dict(relic), "rewards": rewards})
    return {"id": session["id"], "user_slot": session["user_slot"], "state": session["state"],
            "chosen_item_id": session["chosen_item_id"], "columns": columns}


def create_session(db: sqlite3.Connection, relic_ids: list[str], user_slot: int) -> dict:
    if user_slot >= len(relic_ids):
        raise HTTPException(422, "user_slot must identify a supplied relic")
    found = db.execute(f"SELECT COUNT(*) FROM relics WHERE id IN ({','.join('?' * len(relic_ids))})", relic_ids).fetchone()[0]
    if found != len(set(relic_ids)):
        # Duplicate squad relics are valid, so compare unique IDs.
        found_unique = db.execute(f"SELECT COUNT(*) FROM relics WHERE id IN ({','.join('?' * len(set(relic_ids)))})", tuple(set(relic_ids))).fetchone()[0]
        if found_unique != len(set(relic_ids)):
            raise HTTPException(422, "Unknown relic")
    session_id = str(uuid.uuid4())
    db.execute("INSERT INTO run_sessions(id,slots_json,user_slot) VALUES(?,?,?)", (session_id, json.dumps(relic_ids), user_slot))
    return session_view(db, session_id)


def confirm_reward(db: sqlite3.Connection, session_id: str, item_id: str, key: str) -> dict:
    existing = db.execute("SELECT id FROM transactions WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        return {"transaction_id": existing["id"], "duplicate": True}
    session = db.execute("SELECT * FROM run_sessions WHERE id=?", (session_id,)).fetchone()
    if not session or session["state"] != "open":
        raise HTTPException(409, "Run is not open")
    slots = json.loads(session["slots_json"])
    valid = db.execute(f"SELECT 1 FROM relic_rewards WHERE item_id=? AND relic_id IN ({','.join('?' * len(slots))})", (item_id, *slots)).fetchone()
    if not valid:
        raise HTTPException(422, "Reward is not in this squad rotation")
    consumed = slots[session["user_slot"]]
    qty = db.execute("SELECT quantity FROM relic_inventory WHERE relic_id=?", (consumed,)).fetchone()
    if not qty or qty["quantity"] < 1:
        raise HTTPException(409, "No copy of the user's relic remains")
    db.execute("UPDATE relic_inventory SET quantity=quantity-1,verified_at=CURRENT_TIMESTAMP WHERE relic_id=?", (consumed,))
    db.execute("INSERT INTO inventory(item_id,quantity) VALUES(?,1) ON CONFLICT(item_id) DO UPDATE SET quantity=quantity+1,verified_at=CURRENT_TIMESTAMP", (item_id,))
    tx_id = str(uuid.uuid4())
    db.execute("INSERT INTO transactions(id,session_id,item_id,consumed_relic_id,idempotency_key) VALUES(?,?,?,?,?)", (tx_id,session_id,item_id,consumed,key))
    db.execute("UPDATE run_sessions SET chosen_item_id=?,state='confirmed' WHERE id=?", (item_id,session_id))
    return {"transaction_id": tx_id, "duplicate": False}


def undo(db: sqlite3.Connection, transaction_id: str) -> None:
    tx = db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()
    if not tx:
        raise HTTPException(404, "Transaction not found")
    if tx["undone"]:
        return
    owned = db.execute("SELECT quantity FROM inventory WHERE item_id=?", (tx["item_id"],)).fetchone()[0]
    if owned < 1:
        raise HTTPException(409, "Inventory changed; cannot safely undo")
    db.execute("UPDATE inventory SET quantity=quantity-1 WHERE item_id=?", (tx["item_id"],))
    if tx["consumed_relic_id"]:
        db.execute("UPDATE relic_inventory SET quantity=quantity+1 WHERE relic_id=?", (tx["consumed_relic_id"],))
    db.execute("UPDATE transactions SET undone=1 WHERE id=?", (transaction_id,))
    db.execute("UPDATE run_sessions SET state='open',chosen_item_id=NULL WHERE id=?", (tx["session_id"],))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
