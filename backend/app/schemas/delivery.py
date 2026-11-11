from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import GeoPoint


class LocationUpdate(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    speed_kmh: float | None = None


class DeliveryPersonOut(BaseModel):
    id: UUID
    name: str
    vehicle_type: str
    is_available: bool
    rating: Decimal
    total_deliveries: int

    class Config:
        from_attributes = True


class DeliveryPersonAvailable(BaseModel):
    id: UUID
    name: str
    vehicle_type: str
    distance_m: float
    rating: Decimal


class TrackLocation(BaseModel):
    lat: float
    lng: float
    speed_kmh: float | None
    recorded_at: str


class DeliveryProfileOut(BaseModel):
    id: UUID
    user_id: UUID
    vehicle_type: str
    is_available: bool
    rating: Decimal
    total_deliveries: int
    payout_method: str
    payout_frequency_days: int
    bank_name: str | None
    bank_account_holder: str | None
    bank_clabe: str | None
    is_mandadero: bool
    pending_platform_debt: Decimal
    delivery_bonus_per_order: Decimal = Decimal("0")
    current_order_id: UUID | None

    class Config:
        from_attributes = True


class DeliveryPersonAdminUpdate(BaseModel):
    delivery_bonus_per_order: Decimal | None = Field(default=None, ge=0)
    payout_frequency_days: int | None = Field(default=None, ge=0, le=90)
    payout_method: str | None = Field(default=None, pattern="^(cash|transfer)$")


class DeliveryPayoutOut(BaseModel):
    id: UUID
    period_start: date
    period_end: date
    orders_count: int
    total_earnings: Decimal
    payout_method: str
    confirmation_code: str
    status: str
    paid_at: datetime | None
    confirmed_at: datetime | None
    notes: str | None

    class Config:
        from_attributes = True


class AvailabilityUpdate(BaseModel):
    is_available: bool


class DeliveryProfileUpdate(BaseModel):
    payout_method: str | None = None
    payout_frequency_days: int | None = None
    bank_name: str | None = None
    bank_account_holder: str | None = None
    bank_clabe: str | None = None


class DeliveryEarningsItem(BaseModel):
    id: UUID
    placed_at: datetime
    total: Decimal
    delivery_earnings: Decimal
    status: str
    payment_method: str


class DeliveryEarningsOut(BaseModel):
    total_deliveries: int
    total_earned: Decimal
    total_transfer_earnings: Decimal
    total_cash_collected: Decimal
    total_paid: Decimal
    total_pending_payouts: Decimal
    total_pending_debt: Decimal
    total_pending_from_platform: Decimal
    total_pending_confirmation: Decimal = Decimal("0")
    total_advance_debt: Decimal = Decimal("0")
    orders: list[DeliveryEarningsItem]

