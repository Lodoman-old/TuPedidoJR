from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import GeoPoint
from app.schemas.order import TrackPoint


class ShipmentQuoteRequest(BaseModel):
    delivery_location: GeoPoint
    collect_amount: Decimal = Field(default=Decimal("0"), ge=0)
    shipping_paid_by: str = Field(default="store", pattern="^(store|recipient)$")


class ShipmentQuoteOut(BaseModel):
    delivery_fee: Decimal
    platform_fee: Decimal
    distance_km: float | None = None
    amount_to_collect: Decimal
    store_charge: Decimal


class ShipmentCreate(BaseModel):
    recipient_name: str = Field(..., min_length=2, max_length=150)
    recipient_phone: str = Field(..., min_length=8, max_length=20)
    delivery_address: str = Field(..., min_length=5, max_length=500)
    delivery_location: GeoPoint
    delivery_references: str | None = Field(default=None, max_length=500)
    package_description: str = Field(..., min_length=3, max_length=500)
    declared_value: Decimal = Field(default=Decimal("0"), ge=0)
    collect_amount: Decimal = Field(default=Decimal("0"), ge=0)
    shipping_paid_by: str = Field(default="store", pattern="^(store|recipient)$")
    tip_amount: Decimal = Field(default=Decimal("0"), ge=0)


class ShipmentOut(BaseModel):
    id: UUID
    store_id: UUID
    created_by_id: UUID
    delivery_person_id: UUID | None
    status: str
    recipient_name: str
    recipient_phone: str
    delivery_address: str
    delivery_references: str | None = None
    package_description: str
    declared_value: Decimal
    collect_amount: Decimal
    amount_to_collect: Decimal
    shipping_paid_by: str
    delivery_fee: Decimal
    platform_fee: Decimal
    distance_km: Decimal | None = None
    tip_amount: Decimal
    store_charge: Decimal
    store_credit: Decimal
    store_charge_settled: bool = False
    store_credit_settled: bool = False
    courier_earnings: Decimal
    cash_collected: Decimal
    cash_remitted: bool = False
    payment_status: str
    cod_status: str
    pickup_code: str | None = None
    delivery_code: str | None = None
    public_token: str
    pickup_photo_url: str | None = None
    delivery_photo_url: str | None = None
    accepted_at: datetime | None = None
    picked_up_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    failure_reason: str | None = None
    return_fee: Decimal = Decimal("0")
    created_at: datetime

    class Config:
        from_attributes = True


class ShipmentPickup(BaseModel):
    pickup_photo_url: str | None = Field(default=None, max_length=1000)


class ShipmentDeliver(BaseModel):
    delivery_photo_url: str | None = Field(default=None, max_length=1000)
    delivery_code: str | None = Field(default=None, max_length=4)
    cash_collected: Decimal | None = Field(default=None, ge=0)


class ShipmentFail(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class ShipmentCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ShipmentTrackingStep(BaseModel):
    key: str
    label: str
    completed: bool
    at: datetime | None = None


class ShipmentTrackingOut(BaseModel):
    shipment_id: UUID
    status: str
    store_name: str
    store_logo_url: str | None = None
    recipient_name: str
    delivery_address: str
    package_description: str
    amount_to_collect: Decimal
    timeline: list[ShipmentTrackingStep]
    destination: TrackPoint | None = None
    courier: TrackPoint | None = None
    distance_km: float | None = None
    eta_min: int | None = None
    delivery_code: str | None = None
