from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import GeoPoint


class OrderItemCreate(BaseModel):
    menu_item_id: str
    quantity: int = Field(..., ge=1, le=99)
    notes: str | None = None
    option_ids: list[str] = Field(default_factory=list)


class OrderCreate(BaseModel):
    restaurant_id: str
    items: list[OrderItemCreate] = Field(..., min_length=1)
    delivery_address: str | None = Field(default=None, min_length=5)
    delivery_location: GeoPoint | None = None
    notes: str | None = None
    coupon_code: str | None = None
    payment_method: str = "cash"
    tip_amount: Decimal = Field(default=Decimal("0"), ge=0, le=1000)
    scheduled_for: datetime | None = None
    points_to_redeem: int = Field(default=0, ge=0, le=100000)
    fulfillment_type: str = Field(default="delivery", pattern="^(delivery|pickup)$")
    refund_account_holder: str | None = Field(default=None, max_length=150)
    refund_bank: str | None = Field(default=None, max_length=100)
    refund_clabe: str | None = Field(default=None, max_length=18)


class OrderItemOptionOut(BaseModel):
    option_id: UUID | None = None
    name: str
    group_name: str
    price_delta: Decimal
    portion: Decimal = Decimal("1.0")

    class Config:
        from_attributes = True


class OrderItemOut(BaseModel):
    id: UUID
    menu_item_id: UUID
    name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    notes: str | None
    options: list[OrderItemOptionOut] = []

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: UUID
    user_id: UUID
    restaurant_id: UUID
    delivery_person_id: UUID | None
    status: str
    subtotal: Decimal
    delivery_fee: Decimal
    total: Decimal
    delivery_address: str
    notes: str | None
    estimated_delivery_min: int | None
    payment_method: str
    payment_status: str
    payment_id: str | None
    preference_id: str | None
    coupon_code: str | None
    discount_amount: Decimal
    platform_commission: Decimal
    flat_usage_fee: Decimal
    delivery_earnings: Decimal
    tip_amount: Decimal = Decimal("0")
    scheduled_for: datetime | None = None
    delivery_mode: str = "platform"
    fulfillment_type: str = "delivery"
    restaurant_owes_platform: Decimal = Decimal("0")
    points_redeemed: int = 0
    loyalty_discount: Decimal = Decimal("0")
    requires_courier_approval: bool = False
    awaiting_courier_at: datetime | None = None
    courier_approval_deadline: datetime | None = None
    refund_account_holder: str | None = None
    refund_bank: str | None = None
    refund_clabe: str | None = None
    placed_at: datetime
    confirmed_at: datetime | None
    picked_up_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None = None
    cancelled_by: UUID | None = None
    cancellation_reason: str | None = None
    refund_amount: Decimal = Decimal("0")
    refund_status: str = "none"
    items: list[OrderItemOut] = []

    class Config:
        from_attributes = True


class CancelOrderRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class RefundAccountUpdate(BaseModel):
    refund_account_holder: str = Field(..., min_length=3, max_length=150)
    refund_bank: str = Field(..., min_length=2, max_length=100)
    refund_clabe: str = Field(..., min_length=1, max_length=30)


class CancellationPolicyOut(BaseModel):
    customer_allowed_statuses: list[str]
    restaurant_allowed_statuses: list[str]
    window_min: int
    refund_enabled: bool
    customer_message: str


class AvailableOrderOut(OrderOut):
    restaurant_name: str | None = None
    restaurant_lat: float | None = None
    restaurant_lng: float | None = None
    distance_km: float | None = None
    eta_min: int | None = None


class OrderStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(pending|confirmed|awaiting_courier|preparing|ready|in_delivery|picked_up|delivered|cancelled)$")


class TrackPoint(BaseModel):
    lat: float
    lng: float


class TrackingStep(BaseModel):
    key: str
    label: str
    completed: bool
    at: datetime | None = None


class TrackingOut(BaseModel):
    order_id: UUID
    status: str
    timeline: list[TrackingStep]
    restaurant: TrackPoint | None
    destination: TrackPoint | None
    courier: TrackPoint | None
    distance_km: float | None
    eta_min: int | None
    estimated_delivery_min: int | None
    courier_updated_at: datetime | None
