from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import GeoPoint


class SavedAddressCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    address: str = Field(..., min_length=5)
    location: GeoPoint
    is_default: bool = False
    notes: str | None = None


class SavedAddressUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, min_length=5)
    location: GeoPoint | None = None
    is_default: bool | None = None
    notes: str | None = None


class SavedAddressOut(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    address: str
    location: GeoPoint | None = None
    is_default: bool
    notes: str | None

    class Config:
        from_attributes = True
