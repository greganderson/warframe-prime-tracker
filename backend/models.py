from sqlmodel import SQLModel, Field

class PrimeItem(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    name: str
    is_vaulted: str
