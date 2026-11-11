from sqlalchemy import Column, Date, DateTime, DECIMAL, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class DeliveryPayout(TimestampMixin, Base):
    __tablename__ = "delivery_payouts"

    delivery_person_id = Column(UUID(as_uuid=True), ForeignKey("delivery_persons.id"), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    orders_count = Column(Integer, default=0, nullable=False)
    total_earnings = Column(DECIMAL(10, 2), default=0, nullable=False)
    payout_method = Column(String(10), nullable=False)
    confirmation_code = Column(String(6), nullable=False)
    status = Column(String(15), default="pending", nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
