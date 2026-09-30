from __future__ import annotations

import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from sqlmodel import delete, select

from . import db as database
from . import voice
from .db import (AppMetadata, EquipmentProgress, Inventory, Item, MODEL_BY_TABLE,
                 MODELS, Relic, Session, engine, now, session_scope)
from .models import (PriceRequest, ProgressChange, QuantityChange, RewardConfirm,
                     RunCreate, SettingsChange)
from .market import refresh_market_prices
from .public_export import CatalogRefreshError, refresh_full_catalog
from .services import build_equipment, collection, confirm_reward, create_session, session_view, undo, utc_now


@asynccontextmanager
async def lifespan(_:FastAPI): database.initialize(); yield

app=FastAPI(title="Warframe Prime Tracker",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_methods=["*"],allow_headers=["*"])

@app.get("/api/v1/health")
def health(): return {"status":"ok","time":utc_now()}

@app.get("/api/v1/settings")
def get_settings():
    with Session(engine) as session:
        record=session.get(AppMetadata,"platinum_highlight_threshold")
        return {"platinum_highlight_threshold":int(record.value) if record else 20}

@app.patch("/api/v1/settings")
def change_settings(body:SettingsChange):
    with session_scope() as session:
        record=session.get(AppMetadata,"platinum_highlight_threshold")
        value=str(body.platinum_highlight_threshold)
        if record: record.value=value
        else: session.add(AppMetadata(key="platinum_highlight_threshold",value=value))
        return body.model_dump()

@app.get("/api/v1/catalog/relics")
def relics(era:str|None=None):
    with Session(engine) as session:
        statement=select(Relic)
        if era: statement=statement.where(Relic.era==era)
        return session.exec(statement.order_by(Relic.era,Relic.code)).all()

@app.post("/api/v1/catalog/relics/refresh")
def refresh_relics():
    try: return {**refresh_full_catalog(),"refreshed_at":utc_now()}
    except CatalogRefreshError as error:
        with session_scope() as session:
            record=session.get(AppMetadata,"relic_catalog_error")
            value=f"{error.stage}: {error}"
            if record: record.value=value
            else: session.add(AppMetadata(key="relic_catalog_error",value=value))
        raise HTTPException(502,{"message":"Official relic catalog refresh failed","stage":error.stage,"reason":str(error)})

@app.get("/api/v1/catalog/relics/status")
def relic_catalog_status():
    with Session(engine) as session:
        records=session.exec(select(AppMetadata).where(AppMetadata.key.startswith("relic_catalog_"))).all()
        return {"count":len(session.exec(select(Relic)).all()),**{record.key:record.value for record in records}}

@app.post("/api/v1/market/prices")
def market_prices(body:PriceRequest):
    try: return refresh_market_prices(body.item_ids)
    except Exception as error: raise HTTPException(502,f"Market refresh failed: {error}")

@app.get("/api/v1/collection")
def get_collection():
    with Session(engine) as session: return collection(session)

@app.patch("/api/v1/inventory/{item_id}")
def change_inventory(item_id:str,body:QuantityChange):
    with session_scope() as session:
        inventory=session.get(Inventory,item_id)
        if not inventory: raise HTTPException(404,"Inventory item not found")
        if inventory.quantity+body.delta<0: raise HTTPException(409,"Quantity cannot be negative")
        inventory.quantity+=body.delta; inventory.verified_at=now()
        return {"item_id":item_id,"quantity":inventory.quantity}

@app.patch("/api/v1/equipment/{equipment_id}")
def change_progress(equipment_id:str,body:ProgressChange):
    updates=body.model_dump(exclude_none=True)
    with session_scope() as session:
        progress=session.get(EquipmentProgress,equipment_id)
        if not progress: raise HTTPException(404,"Equipment not found")
        for key,value in updates.items(): setattr(progress,key,value)
        return {"equipment_id":equipment_id,**updates}

@app.post("/api/v1/equipment/{equipment_id}/build")
def build_set(equipment_id:str):
    with session_scope() as session: return build_equipment(session,equipment_id)

@app.post("/api/v1/runs",status_code=201)
def start_run(body:RunCreate):
    with session_scope() as session: return create_session(session,body.relic_ids)

@app.get("/api/v1/runs/{session_id}")
def get_run(session_id:str):
    with Session(engine) as session: return session_view(session,session_id)

@app.post("/api/v1/runs/{session_id}/confirm")
def confirm(session_id:str,body:RewardConfirm):
    with session_scope() as session: return confirm_reward(session,session_id,body.item_id,body.idempotency_key)

@app.post("/api/v1/transactions/{transaction_id}/undo")
def undo_transaction(transaction_id:str):
    with session_scope() as session: undo(session,transaction_id); return {"undone":True}

@app.get("/api/v1/voice/status")
def voice_status(): return {"available":voice.available()}

@app.websocket("/api/v1/voice")
async def voice_dictation(websocket:WebSocket,rate:float=16000,era:str|None=None):
    """Stream 16-bit mono PCM in; send partial transcripts and parsed relics out. Send "stop" to finish."""
    await websocket.accept()
    if not voice.available():
        await websocket.send_json({"error":"Voice model is not installed"}); await websocket.close(); return
    with Session(engine) as session:
        relics=[relic.model_dump() for relic in session.exec(select(Relic)).all()]
    recognizer=await run_in_threadpool(voice.recognizer,rate); segments:list[str]=[]
    def update(partial:str=""):
        text=" ".join(filter(None,[*segments,partial])); return {"text":text,"relics":voice.parse(text,relics,era)}
    try:
        while True:
            message=await websocket.receive()
            if message["type"]=="websocket.disconnect": return
            if message.get("text")=="stop":
                segments.append(json.loads(await run_in_threadpool(recognizer.FinalResult))["text"])
                await websocket.send_json({**update(),"done":True}); await websocket.close(); return
            if not message.get("bytes"): continue
            if await run_in_threadpool(recognizer.AcceptWaveform,message["bytes"]):
                segments.append(json.loads(recognizer.Result())["text"]); await websocket.send_json(update())
            else: await websocket.send_json(update(json.loads(recognizer.PartialResult())["partial"]))
    except WebSocketDisconnect: return

def _model_rows(session:Session,model:type)->list[dict]:
    return [row.model_dump(mode="json") for row in session.exec(select(model)).all()]

@app.get("/api/v1/backup")
def backup():
    with Session(engine) as session:
        payload={"version":1,"exported_at":utc_now(),"tables":{model.__tablename__:_model_rows(session,model) for model in MODELS}}
    return Response(json.dumps(payload,indent=2),media_type="application/json",headers={"Content-Disposition":"attachment; filename=warframe-tracker-backup.json"})

@app.post("/api/v1/backup/restore")
async def restore(file:UploadFile=File(...)):
    try: data=json.loads((await file.read()).decode())
    except (UnicodeDecodeError,json.JSONDecodeError) as error: raise HTTPException(422,f"Invalid JSON backup: {error}")
    if data.get("version")!=1 or not isinstance(data.get("tables"),dict): raise HTTPException(422,"Unsupported backup")
    with session_scope() as session:
        for model in reversed(MODELS): session.exec(delete(model))
        session.flush()
        for table,model in MODEL_BY_TABLE.items():
            for row in data["tables"].get(table,[]): session.add(model.model_validate(row))
    return {"restored":True}

@app.get("/api/v1/inventory.csv")
def export_csv():
    output=io.StringIO(); writer=csv.writer(output); writer.writerow(["item_id","name","type","quantity"])
    with Session(engine) as session:
        for item in session.exec(select(Item).where(Item.kind!="equipment").order_by(Item.name)).all():
            inventory=session.get(Inventory,item.id); writer.writerow([item.id,item.name,item.kind,inventory.quantity if inventory else 0])
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=inventory.csv"})

@app.post("/api/v1/inventory/import")
async def import_csv(file:UploadFile=File(...)):
    rows=list(csv.DictReader(io.StringIO((await file.read()).decode("utf-8-sig")))); changed=0
    with session_scope() as session:
        for row in rows:
            try: quantity=int(row["quantity"])
            except (KeyError,ValueError): raise HTTPException(422,"CSV requires item_id and non-negative integer quantity")
            item=session.get(Item,row.get("item_id"));
            if quantity<0 or not item: raise HTTPException(422,f"Invalid item: {row.get('item_id')}")
            inventory=session.get(Inventory,item.id)
            if inventory: inventory.quantity=quantity; inventory.verified_at=now()
            else: session.add(Inventory(item_id=item.id,quantity=quantity))
            changed+=1
    return {"imported":changed}

dist=Path(__file__).parents[2]/"frontend"/"dist"
if dist.exists():
    app.mount("/assets",StaticFiles(directory=dist/"assets"),name="assets")
    @app.get("/{path:path}")
    def spa(path:str):
        candidate=dist/path
        return FileResponse(candidate if candidate.is_file() else dist/"index.html")
