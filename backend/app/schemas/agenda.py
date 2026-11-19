from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    duration_min: int = Field(default=30, ge=5, le=480)
    price: Decimal = Field(default=Decimal("0"), ge=0)
    is_active: bool = True
    sort_order: int = 0


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    duration_min: int | None = Field(default=None, ge=5, le=480)
    price: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None
    sort_order: int | None = None


class ServiceOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    duration_min: int
    price: Decimal
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: str | None = Field(default=None, max_length=60)
    is_active: bool = True
    sort_order: int = 0


class StaffUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None
    sort_order: int | None = None


class StaffOut(BaseModel):
    id: UUID
    name: str
    role: str | None
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


class AppointmentIn(BaseModel):
    service_id: UUID
    staff_id: UUID | None = None
    start_at: str
    client_name: str = Field(min_length=1, max_length=120)
    client_phone: str | None = Field(default=None, max_length=25)
    notes: str | None = None
    payment_mode: str = Field(default="cash", pattern="^(cash|deposit|full)$")
    proof_url: str | None = None


class AppointmentProof(BaseModel):
    proof_url: str = Field(min_length=1)


class AppointmentReassign(BaseModel):
    staff_id: UUID


class AppointmentStatusUpdate(BaseModel):
    status: str = Field(pattern="^(confirmed|completed|cancelled|no_show)$")


class AppointmentOut(BaseModel):
    id: UUID
    restaurant_id: UUID
    service_id: UUID | None
    staff_id: UUID | None
    service_name: str | None = None
    staff_name: str | None = None
    restaurant_name: str | None = None
    client_name: str
    client_phone: str | None
    start_at: datetime
    end_at: datetime
    status: str
    price: Decimal
    payment_mode: str
    payment_status: str
    deposit_amount: Decimal = Decimal("0")
    deposit_percent: Decimal = Decimal("0")
    online_amount: Decimal = Decimal("0")
    cash_due: Decimal = Decimal("0")
    business_credit: Decimal = Decimal("0")
    business_debt: Decimal = Decimal("0")
    platform_fee: Decimal
    business_fee: Decimal
    payment_reference: str | None = None
    receipt_status: str = "none"
    proof_url: str | None = None
    paid_at: datetime | None = None
    refund_amount: Decimal = Decimal("0")
    reassign_status: str = "none"
    reassign_requested_at: datetime | None = None
    notes: str | None
