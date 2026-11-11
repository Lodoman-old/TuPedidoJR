from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CashAdvanceCreate(BaseModel):
    order_id: str
    notes: str | None = Field(default=None, max_length=300)


class CashAdvanceApprove(BaseModel):
    pays_restaurant: bool = True


class CashAdvanceOut(BaseModel):
    id: UUID
    delivery_person_id: UUID
    order_id: UUID | None
    mandado_id: UUID | None
    amount: Decimal
    status: str
    pays_restaurant: bool
    settlement_method: str | None
    taken_at: datetime
    settled_at: datetime | None
    notes: str | None

    class Config:
        from_attributes = True


class AdminCashAdvanceOut(CashAdvanceOut):
    courier_name: str | None = None
    restaurant_name: str | None = None
