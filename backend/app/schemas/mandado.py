from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import GeoPoint
from app.schemas.order import TrackPoint


class MandadoCreate(BaseModel):
    description: str = Field(..., min_length=10)
    estimated_budget: Decimal = Field(..., gt=0)
    delivery_address: str = Field(..., min_length=5)
    delivery_location: GeoPoint
    payment_method: str = "cash"
    payment_proof_url: str | None = Field(default=None, max_length=1000)


class MandadoPaymentPolicyOut(BaseModel):
    requires_prepayment: bool
    trusted_customer: bool
    threshold: Decimal
    max_cash: Decimal
    payment_methods: list[str] = ["cash", "transfer", "mp"]


class MandadoPaymentPolicyRequest(BaseModel):
    estimated_budget: Decimal = Field(..., gt=0)


class MandadoEstimateRequest(BaseModel):
    estimated_budget: Decimal = Field(..., gt=0)
    delivery_location: GeoPoint


class MandadoEstimateOut(BaseModel):
    estimated_budget: Decimal
    delivery_fee: Decimal
    distance_km: float | None = None
    risk_type: str
    risk_value: Decimal
    risk_fee: Decimal
    platform_fee: Decimal
    estimated_total: Decimal


class MandadoOut(BaseModel):
    id: UUID
    user_id: UUID
    delivery_person_id: UUID | None
    description: str
    estimated_budget: Decimal
    product_total: Decimal | None
    delivery_fee: Decimal
    risk_fee: Decimal
    platform_fee: Decimal
    estimated_total: Decimal
    final_total: Decimal | None
    payment_method: str
    payment_status: str
    prepayment_required: bool = False
    prepayment_proof_url: str | None = None
    prepayment_confirmed_at: datetime | None = None
    advance_amount: Decimal = Decimal("0")
    advance_status: str = "not_required"
    advance_difference: Decimal | None = None
    advance_delivered_at: datetime | None = None
    advance_settled_at: datetime | None = None
    status: str
    delivery_address: str
    receipt_photo_url: str | None
    accepted_at: datetime | None
    purchased_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class MandadoAccept(BaseModel):
    pass


class MandadoPurchase(BaseModel):
    product_total: Decimal = Field(..., gt=0)
    receipt_photo_url: str = Field(..., min_length=1)


class MandadoPaymentProof(BaseModel):
    proof_url: str = Field(..., min_length=1, max_length=1000)


class MandadoTrackingStep(BaseModel):
    key: str
    label: str
    completed: bool
    at: datetime | None = None


class MandadoTrackingOut(BaseModel):
    mandado_id: UUID
    status: str
    timeline: list[MandadoTrackingStep]
    destination: TrackPoint | None = None
    courier: TrackPoint | None = None
    distance_km: float | None = None
    eta_min: int | None = None
    estimated_total: Decimal
    final_total: Decimal | None = None
    payment_method: str
