import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, DECIMAL, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class CashAdvance(Base):
    __tablename__ = "cash_advances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_person_id = Column(UUID(as_uuid=True), ForeignKey("delivery_persons.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    mandado_id = Column(UUID(as_uuid=True), ForeignKey("mandados.id"), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    amount = Column(DECIMAL(10, 2), nullable=False)
    status = Column(String(15), default="pending", nullable=False)
    pays_restaurant = Column(Boolean, default=True, nullable=False)
    settlement_method = Column(String(20), nullable=True)
    taken_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
