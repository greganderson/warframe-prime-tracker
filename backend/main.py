from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from database import get_db
from models import PrimeItem
from schemas import CreatePrimeItemRequest, CreatePrimeItemResponse, DeletePrimeItemResponse
app = FastAPI(title="Warframe Prime Tracker API", version="0.0.0")

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/built-items")
async def get_built_items(db: Session = Depends(get_db)) -> list[PrimeItem]:
    return db.exec(select(PrimeItem)).all()

@app.post("/built-items")
async def add_built_item(item: CreatePrimeItemRequest, db: Session = Depends(get_db)) -> CreatePrimeItemResponse:
    db.add(PrimeItem(name=item.name, is_vaulted=item.is_vaulted))
    db.commit()
    return CreatePrimeItemResponse(message="Item added successfully")

@app.delete("/built-items/{item_id}")
async def delete_built_item(item_id: int, db: Session = Depends(get_db)) -> DeletePrimeItemResponse:
    db.delete(db.get(PrimeItem, item_id))
    db.commit()
    return DeletePrimeItemResponse(message="Item deleted successfully")
