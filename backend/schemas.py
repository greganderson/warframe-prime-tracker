from pydantic import BaseModel

class CreatePrimeItemRequest(BaseModel):
    name: str
    is_vaulted: str

class CreatePrimeItemResponse(BaseModel):
    message: str

class DeletePrimeItemResponse(BaseModel):
    message: str
