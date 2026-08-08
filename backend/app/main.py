from __future__ import annotations

import csv
import io
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db as database
from .models import ProgressChange, QuantityChange, RewardConfirm, RunCreate
from .services import collection, confirm_reward, create_session, session_view, undo, utc_now


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(title="Warframe Prime Tracker", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "time": utc_now()}


@app.get("/api/v1/catalog/relics")
def relics(era: str | None = None):
    with database.connect() as db:
        rows = db.execute("""SELECT r.*,COALESCE(i.quantity,0) owned FROM relics r
            LEFT JOIN relic_inventory i ON i.relic_id=r.id WHERE (? IS NULL OR r.era=?) ORDER BY r.era,r.code""", (era,era)).fetchall()
        return [dict(x) for x in rows]


@app.get("/api/v1/collection")
def get_collection():
    with database.connect() as db:
        return collection(db)


@app.patch("/api/v1/inventory/{item_id}")
def change_inventory(item_id: str, body: QuantityChange):
    with database.transaction() as db:
        row = db.execute("SELECT quantity FROM inventory WHERE item_id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Inventory item not found")
        quantity = row["quantity"] + body.delta
        if quantity < 0:
            raise HTTPException(409, "Quantity cannot be negative")
        db.execute("UPDATE inventory SET quantity=?,verified_at=CURRENT_TIMESTAMP WHERE item_id=?", (quantity,item_id))
        return {"item_id": item_id, "quantity": quantity}


@app.patch("/api/v1/relics/{relic_id}")
def change_relic(relic_id: str, body: QuantityChange):
    with database.transaction() as db:
        row = db.execute("SELECT quantity FROM relic_inventory WHERE relic_id=?", (relic_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Relic not found")
        quantity = row["quantity"] + body.delta
        if quantity < 0:
            raise HTTPException(409, "Quantity cannot be negative")
        db.execute("UPDATE relic_inventory SET quantity=?,verified_at=CURRENT_TIMESTAMP WHERE relic_id=?", (quantity,relic_id))
        return {"relic_id": relic_id, "quantity": quantity}


@app.patch("/api/v1/equipment/{equipment_id}")
def change_progress(equipment_id: str, body: ProgressChange):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {}
    with database.transaction() as db:
        if not db.execute("SELECT 1 FROM equipment_progress WHERE equipment_id=?", (equipment_id,)).fetchone():
            raise HTTPException(404, "Equipment not found")
        db.execute(f"UPDATE equipment_progress SET {','.join(f'{k}=?' for k in updates)} WHERE equipment_id=?", (*[int(v) for v in updates.values()],equipment_id))
        return {"equipment_id": equipment_id, **updates}


@app.post("/api/v1/runs", status_code=201)
def start_run(body: RunCreate):
    with database.transaction() as db:
        return create_session(db, body.relic_ids, body.user_slot)


@app.get("/api/v1/runs/{session_id}")
def get_run(session_id: str):
    with database.connect() as db:
        return session_view(db, session_id)


@app.post("/api/v1/runs/{session_id}/confirm")
def confirm(session_id: str, body: RewardConfirm):
    with database.transaction() as db:
        return confirm_reward(db, session_id, body.item_id, body.idempotency_key)


@app.post("/api/v1/transactions/{transaction_id}/undo")
def undo_transaction(transaction_id: str):
    with database.transaction() as db:
        undo(db, transaction_id)
        return {"undone": True}


@app.get("/api/v1/backup")
def backup():
    with database.connect() as db:
        tables = ["items","equipment","recipes","relics","relic_rewards","inventory","relic_inventory","equipment_progress","run_sessions","transactions","metadata"]
        payload = {"version": 1, "exported_at": utc_now(), "tables": {t: [dict(x) for x in db.execute(f"SELECT * FROM {t}")] for t in tables}}
    return Response(json.dumps(payload, indent=2), media_type="application/json", headers={"Content-Disposition":"attachment; filename=warframe-tracker-backup.json"})


@app.post("/api/v1/backup/restore")
async def restore(file: UploadFile = File(...)):
    data = json.loads((await file.read()).decode())
    if data.get("version") != 1 or "tables" not in data:
        raise HTTPException(422, "Unsupported backup")
    allowed = ["items","equipment","recipes","relics","relic_rewards","inventory","relic_inventory","equipment_progress","run_sessions","transactions","metadata"]
    with database.transaction() as db:
        for table in reversed(allowed): db.execute(f"DELETE FROM {table}")
        for table in allowed:
            for row in data["tables"].get(table, []):
                cols = list(row)
                db.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?'*len(cols))})", tuple(row[c] for c in cols))
    return {"restored": True}


@app.get("/api/v1/inventory.csv")
def export_csv():
    out = io.StringIO(); writer = csv.writer(out); writer.writerow(["item_id","name","type","quantity"])
    with database.connect() as db:
        for row in db.execute("SELECT i.id,i.name,i.kind,COALESCE(v.quantity,0) quantity FROM items i LEFT JOIN inventory v ON v.item_id=i.id WHERE i.kind!='equipment' ORDER BY i.name"):
            writer.writerow(row)
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition":"attachment; filename=inventory.csv"})


@app.post("/api/v1/inventory/import")
async def import_csv(file: UploadFile = File(...)):
    rows = list(csv.DictReader(io.StringIO((await file.read()).decode("utf-8-sig"))))
    changed = 0
    with database.transaction() as db:
        for row in rows:
            try: quantity = int(row["quantity"])
            except (KeyError, ValueError): raise HTTPException(422, "CSV requires item_id and non-negative integer quantity")
            if quantity < 0 or not db.execute("SELECT 1 FROM items WHERE id=?", (row.get("item_id"),)).fetchone():
                raise HTTPException(422, f"Invalid item: {row.get('item_id')}")
            db.execute("INSERT INTO inventory(item_id,quantity) VALUES(?,?) ON CONFLICT(item_id) DO UPDATE SET quantity=excluded.quantity,verified_at=CURRENT_TIMESTAMP", (row["item_id"],quantity)); changed += 1
    return {"imported": changed}


dist = Path(__file__).parents[2] / "frontend" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    @app.get("/{path:path}")
    def spa(path: str):
        candidate = dist / path
        return FileResponse(candidate if candidate.is_file() else dist / "index.html")
