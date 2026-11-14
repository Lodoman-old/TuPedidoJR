from sqlalchemy import Boolean, Column, DateTime, DECIMAL, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, TimestampMixin


class Reservation(TimestampMixin, Base):
    __tablename__ = "reservations"

    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reservation_at = Column(DateTime(timezone=True), nullable=False)
    party_size = Column(Integer, default=2, nullable=False)
    status = Column(String(30), default="requested", nullable=False)
    notes = Column(Text, nullable=True)

    preorder_items = Column(JSONB, nullable=True)
    preorder_subtotal = Column(DECIMAL(10, 2), default=0, nullable=False)
    service_fee = Column(DECIMAL(10, 2), default=0, nullable=False)
    service_fee_cash = Column(Boolean, default=False, nullable=False)
    service_fee_status = Column(String(20), default="pending", nullable=False)
    deposit_percent = Column(DECIMAL(5, 2), default=20, nullable=False)
    deposit_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    deposit_status = Column(String(20), default="not_required", nullable=False)
    deposit_method = Column(String(20), nullable=True)
    deposit_proof_url = Column(Text, nullable=True)
    commission_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    commission_status = Column(String(20), default="pending", nullable=False)
    remaining_to_charge = Column(DECIMAL(10, 2), default=0, nullable=False)
    deposit_settlement_status = Column(
        String(20), default="not_required", nullable=False
    )

    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    seated_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    no_show_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    cancellation_reason = Column(Text, nullable=True)
