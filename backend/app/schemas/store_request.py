from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import GeoPoint


class StoreRequestCreate(BaseModel):
    description: str = Field(..., min_length=5, max_length=500)
    quantity: int = Field(default=1, ge=1, le=50)
    budget: Decimal | None = Field(default=None, ge=0)
    reference_photo_url: str | None = Field(default=None, max_length=1000)
    delivery_address: str = Field(..., min_length=5, max_length=500)
    delivery_location: GeoPoint
    payment_method: str = Field(default="cash", pattern="^(cash|transfer|mp)$")
    notes: str | None = Field(default=None, max_length=500)


class StoreRequestRespond(BaseModel):
    status: str = Field(..., pattern="^(quoted|rejected)$")
    quoted_price: Decimal | None = Field(default=None, ge=0)
    store_notes: str | None = Field(default=None, max_length=500)


class StoreRequestOut(BaseModel):
    id: UUID
    store_id: UUID
    store_name: str | None = None
    store_logo_url: str | None = None
    user_id: UUID
    customer_name: str | None = None
    customer_phone: str | None = None
    description: str
    quantity: int
    reference_photo_url: str | None = None
    budget: Decimal | None = None
    status: str
    quoted_price: Decimal | None = None
    store_notes: str | None = None
    delivery_address: str
    payment_method: str
    notes: str | None = None
    order_id: UUID | None = None
    responded_at: datetime | None = None
    confirmed_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True
