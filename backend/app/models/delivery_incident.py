from sqlalchemy import Boolean, Column, DateTime, DECIMAL, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class DeliveryIncident(TimestampMixin, Base):
    __tablename__ = "delivery_incidents"

    entity_type = Column(String(20), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    courier_id = Column(UUID(as_uuid=True), ForeignKey("delivery_persons.id"), nullable=True)
    reason_code = Column(String(30), nullable=False)
    notes = Column(Text, nullable=True)
    photo_url = Column(Text, nullable=True)
    lat = Column(DECIMAL(10, 7), nullable=True)
    lng = Column(DECIMAL(10, 7), nullable=True)
    item_kind = Column(String(20), default="food", nullable=False)
    status = Column(String(20), default="reported", nullable=False)

    product_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    delivery_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    redelivery_fee = Column(DECIMAL(10, 2), default=0, nullable=False)
    courier_pay = Column(DECIMAL(10, 2), default=0, nullable=False)
    business_pay = Column(DECIMAL(10, 2), default=0, nullable=False)
    customer_refund = Column(DECIMAL(10, 2), default=0, nullable=False)
    customer_debt = Column(DECIMAL(10, 2), default=0, nullable=False)
    platform_cost = Column(DECIMAL(10, 2), default=0, nullable=False)

    requires_authorization = Column(Boolean, default=False, nullable=False)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_notes = Column(Text, nullable=True)

    custody_code = Column(String(12), nullable=True)
    custody_at = Column(DateTime(timezone=True), nullable=True)
    custody_photo_url = Column(Text, nullable=True)
    holding_until = Column(DateTime(timezone=True), nullable=True)
    redelivery_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
