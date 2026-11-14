from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ReservationItemIn(BaseModel):
    menu_item_id: str
    quantity: int = Field(..., ge=1, le=50)
    option_ids: list[str] = Field(default_factory=list)


class ReservationCreate(BaseModel):
    reservation_at: datetime
    party_size: int = Field(default=2, ge=1, le=20)
    notes: str | None = Field(default=None, max_length=500)
    items: list[ReservationItemIn] = Field(default_factory=list)
    deposit_method: str | None = Field(default="transfer", pattern="^(transfer|mp)$")
    deposit_proof_url: str | None = None


class ReservationDepositProof(BaseModel):
    proof_url: str = Field(..., min_length=3, max_length=1000)


class ReservationStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(confirmed|rejected|seated|completed|no_show|cancelled)$")
    reason: str | None = Field(default=None, max_length=300)


class ReservationOut(BaseModel):
    id: UUID
    restaurant_id: UUID
    restaurant_name: str | None = None
    restaurant_address: str | None = None
    restaurant_phone: str | None = None
    restaurant_slug: str | None = None
    restaurant_logo_url: str | None = None
    user_id: UUID
    user_name: str | None = None
    user_phone: str | None = None
    user_email: str | None = None
    reservation_at: datetime
    party_size: int
    status: str
    notes: str | None
    preorder_items: list[dict] | None = None
    preorder_subtotal: Decimal
    service_fee: Decimal
    service_fee_cash: bool
    service_fee_status: str
    deposit_percent: Decimal
    deposit_amount: Decimal
    deposit_status: str
    deposit_method: str | None
    deposit_proof_url: str | None
    commission_amount: Decimal
    commission_status: str
    remaining_to_charge: Decimal
    deposit_settlement_status: str
    confirmed_at: datetime | None = None
    seated_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    no_show_at: datetime | None = None
    cancellation_reason: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
