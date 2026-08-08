from typing import Literal
from pydantic import BaseModel, Field

AvailabilityStatus = Literal["farmable", "resurgence", "special", "vaulted", "exclusive", "unknown"]


class QuantityChange(BaseModel):
    delta: int = Field(ge=-9999, le=9999)


class ProgressChange(BaseModel):
    owned: bool | None = None
    mastered: bool | None = None
    favorite: bool | None = None
    target: bool | None = None


class RunCreate(BaseModel):
    relic_ids: list[str] = Field(min_length=1, max_length=4)


class RewardConfirm(BaseModel):
    item_id: str
    idempotency_key: str = Field(min_length=8, max_length=100)


class InventoryImportRow(BaseModel):
    item_id: str
    quantity: int = Field(ge=0)
