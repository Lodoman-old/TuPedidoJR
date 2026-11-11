from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, DECIMAL, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class Coupon(TimestampMixin, Base):
    __tablename__ = "coupons"

    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)
    discount_type = Column(String(10), nullable=False)  # "percentage" or "fixed"
    discount_value = Column(DECIMAL(10, 2), nullable=False)
    min_order_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    max_discount = Column(DECIMAL(10, 2), nullable=True)
    max_uses = Column(Integer, default=0, nullable=False)
    current_uses = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=True)
