from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class RecargaCreate(BaseModel):
    company: str = Field(..., min_length=2, max_length=40)
    phone: str = Field(..., min_length=10, max_length=20)
    amount: Decimal = Field(..., gt=0, le=1000)
    payment_method: str = Field(default="cash", pattern="^(cash|transfer)$")
    order_id: UUID | None = None
    customer_name: str | None = Field(default=None, max_length=150)


class RecargaOut(BaseModel):
    id: UUID
    user_id: UUID | None = None
    customer_name: str | None = None
    delivery_person_id: UUID | None = None
    order_id: UUID | None = None
    order_code: str | None = None
    origin: str | None = None
    courier_name: str | None = None
    company: str
    phone: str
    amount: Decimal
    fee: Decimal
    total: Decimal
    payment_method: str
    payment_status: str
    status: str
    provider_reference: str | None = None
    error_message: str | None = None
    notes: str | None = None
    paid_at: datetime | None = None
    completed_at: datetime | None = None
    refunded_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class RecargaComplete(BaseModel):
    provider_reference: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=500)


class RecargaFail(BaseModel):
    refund: bool = True
    error_message: str | None = Field(default=None, max_length=500)
