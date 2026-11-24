from sqlalchemy import DECIMAL, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, TimestampMixin


class BalancePayment(TimestampMixin, Base):
    """Intento de pago del saldo pendiente de un cliente."""

    __tablename__ = "balance_payments"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    amount = Column(DECIMAL(10, 2), nullable=False)
    status = Column(String(20), default="pending", nullable=False, index=True)
    transfer_tracking_key = Column(
        String(30), nullable=True, unique=True, index=True
    )
    cep_status = Column(String(20), nullable=True)
    cep_validated_at = Column(DateTime(timezone=True), nullable=True)
    cep_sender_bank = Column(String(80), nullable=True)
    cep_receiver_bank = Column(String(80), nullable=True)
    cep_payload = Column(JSONB, nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
