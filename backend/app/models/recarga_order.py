from sqlalchemy import Boolean, Column, DECIMAL, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class RecargaOrder(TimestampMixin, Base):
    __tablename__ = "recarga_orders"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    customer_name = Column(String(150), nullable=True)
    delivery_person_id = Column(
        UUID(as_uuid=True), ForeignKey("delivery_persons.id", ondelete="SET NULL"), nullable=True
    )
    order_id = Column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    origin = Column(String(20), nullable=True, index=True)
    company = Column(String(40), nullable=False)
    phone = Column(String(20), nullable=False)
    amount = Column(DECIMAL(10, 2), nullable=False)
    fee = Column(DECIMAL(10, 2), default=0, nullable=False)
    total = Column(DECIMAL(10, 2), nullable=False)
    payment_method = Column(String(10), default="cash", nullable=False)
    payment_status = Column(String(15), default="pending", nullable=False)
    status = Column(String(15), default="pending", nullable=False)
    provider_reference = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    debt_applied = Column(Boolean, default=False, nullable=False)
    credit_applied = Column(Boolean, default=False, nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
