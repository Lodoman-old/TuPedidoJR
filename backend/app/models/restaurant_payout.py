from sqlalchemy import Column, Date, DateTime, DECIMAL, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class RestaurantPayout(TimestampMixin, Base):
    __tablename__ = "restaurant_payouts"

    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    orders_count = Column(Integer, default=0, nullable=False)
    total_subtotal = Column(DECIMAL(10, 2), default=0, nullable=False)
    total_commission = Column(DECIMAL(10, 2), default=0, nullable=False)
    total_flat_fees = Column(DECIMAL(10, 2), default=0, nullable=False)
    net_payout = Column(DECIMAL(10, 2), default=0, nullable=False)
    status = Column(String(15), default="pending", nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
