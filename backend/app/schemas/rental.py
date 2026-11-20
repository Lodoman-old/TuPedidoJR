from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class RentalItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    duration_min: int = Field(default=240, ge=15, le=1440)
    price: Decimal = Field(default=Decimal("0"), ge=0)
    stock: int = Field(default=1, ge=0, le=9999)
    requires_address: bool = False
    is_active: bool = True
    sort_order: int = 0


class RentalItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    duration_min: int | None = Field(default=None, ge=15, le=1440)
    price: Decimal | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0, le=9999)
    requires_address: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class RentalItemOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    duration_min: int
    price: Decimal
    stock: int
    requires_address: bool
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


class RentalBookingItemIn(BaseModel):
    service_id: UUID
    quantity: int = Field(default=1, ge=1, le=999)
    start_at: str


class RentalBookingIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=120)
    client_phone: str | None = Field(default=None, max_length=25)
    items: list[RentalBookingItemIn] = Field(min_length=1)
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    payment_mode: str = Field(default="cash", pattern="^(cash|deposit|full)$")
    proof_url: str | None = None
    notes: str | None = None


class RentalStatusUpdate(BaseModel):
    status: str = Field(pattern="^(confirmed|completed|cancelled|no_show)$")


class RentalBookingItemOut(BaseModel):
    id: UUID
    service_id: UUID | None
    name: str
    quantity: int
    unit_price: Decimal
    duration_min: int
    start_at: datetime
    end_at: datetime
    subtotal: Decimal


class RentalBookingOut(BaseModel):
    id: UUID
    restaurant_id: UUID
    restaurant_name: str | None = None
    client_name: str
    client_phone: str | None
    start_at: datetime
    end_at: datetime
    address: str | None
    status: str
    payment_mode: str
    payment_status: str
    deposit_amount: Decimal = Decimal("0")
    deposit_percent: Decimal = Decimal("0")
    online_amount: Decimal = Decimal("0")
    cash_due: Decimal = Decimal("0")
    business_credit: Decimal = Decimal("0")
    business_debt: Decimal = Decimal("0")
    platform_fee: Decimal = Decimal("0")
    business_fee: Decimal = Decimal("0")
    proof_url: str | None = None
    receipt_status: str = "none"
    paid_at: datetime | None = None
    refund_amount: Decimal = Decimal("0")
    notes: str | None = None
    items: list[RentalBookingItemOut] = []
