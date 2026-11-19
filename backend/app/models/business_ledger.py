from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class BusinessLedger(TimestampMixin, Base):
    """Movimiento de saldo entre la plataforma y un negocio.

    ``credit`` = la plataforma le debe al negocio.
    ``debit`` = el negocio le debe a la plataforma.
    """

    __tablename__ = "business_ledger"

    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind = Column(String(10), nullable=False)
    amount = Column(Numeric(10, 2), default=0, nullable=False)
    status = Column(String(20), default="pending", nullable=False, index=True)
    notes = Column(Text, nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
