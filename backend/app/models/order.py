from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, DECIMAL, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    delivery_person_id = Column(UUID(as_uuid=True), ForeignKey("delivery_persons.id"), nullable=True)
    status = Column(String(20), default="pending", nullable=False)
    subtotal = Column(DECIMAL(10, 2), nullable=False)
    delivery_fee = Column(DECIMAL(10, 2), nullable=False)
    total = Column(DECIMAL(10, 2), nullable=False)
    delivery_address = Column(Text, nullable=False)
    delivery_location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    notes = Column(Text, nullable=True)
    estimated_delivery_min = Column(Integer, nullable=True)

    payment_method = Column(String(10), default="mp", nullable=False)
    payment_status = Column(String(20), default="pending", nullable=False)
    payment_id = Column(String, nullable=True)
    preference_id = Column(String, nullable=True)

    coupon_id = Column(UUID(as_uuid=True), ForeignKey("coupons.id"), nullable=True)
    coupon_code = Column(String(50), nullable=True)
    discount_amount = Column(DECIMAL(10, 2), default=0, nullable=False)

    platform_commission = Column(DECIMAL(10, 2), default=0, nullable=False)
    flat_usage_fee = Column(DECIMAL(10, 2), default=0, nullable=False)
    delivery_earnings = Column(DECIMAL(10, 2), default=0, nullable=False)
    delivery_distance_km = Column(DECIMAL(8, 2), nullable=True)

    placed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    picked_up_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    refund_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    refund_status = Column(String(20), default="none", nullable=False)
    restaurant_paid_with_advance = Column(Boolean, default=False, nullable=False)
    tip_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    delivery_mode = Column(String(20), default="platform", nullable=False)
    fulfillment_type = Column(String(10), default="delivery", nullable=False)
    restaurant_owes_platform = Column(DECIMAL(10, 2), default=0, nullable=False)
    restaurant_charge_settled = Column(Boolean, default=False, nullable=False)
    arrival_notified = Column(Boolean, default=False, nullable=False)
    points_redeemed = Column(Integer, default=0, nullable=False)
    loyalty_discount = Column(DECIMAL(10, 2), default=0, nullable=False)
    points_awarded = Column(Boolean, default=False, nullable=False)
    requires_courier_approval = Column(Boolean, default=False, nullable=False)
    awaiting_courier_at = Column(DateTime(timezone=True), nullable=True)
    courier_approval_deadline = Column(DateTime(timezone=True), nullable=True)
    refund_account_holder = Column(String(150), nullable=True)
    refund_bank = Column(String(100), nullable=True)
    refund_clabe = Column(String(18), nullable=True)

    items = relationship("OrderItem", backref="order", lazy="selectin")
