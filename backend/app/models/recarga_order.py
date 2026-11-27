from sqlalchemy import Boolean, Column, DECIMAL, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

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
    provider_request_id = Column(String(64), nullable=True, index=True)
    provider_folio = Column(String(40), nullable=True)
    product_code = Column(String(30), nullable=True)
    product_description = Column(String(200), nullable=True)
    product_kind = Column(String(20), nullable=True)
    provider_attempts = Column(Integer, default=0, nullable=False)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    transfer_tracking_key = Column(String(30), nullable=True, unique=True, index=True)
    cep_status = Column(String(20), nullable=True)
    cep_validated_at = Column(DateTime(timezone=True), nullable=True)
    cep_sender_bank = Column(String(80), nullable=True)
    cep_receiver_bank = Column(String(80), nullable=True)
    cep_payload = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    debt_applied = Column(Boolean, default=False, nullable=False)
    credit_applied = Column(Boolean, default=False, nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
