from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class AppointmentDebt(TimestampMixin, Base):
    """Deuda del cliente por una cita a la que no asistió."""

    __tablename__ = "appointment_debts"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="SET NULL"),
        nullable=True,
    )
    appointment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_appointment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount = Column(Numeric(10, 2), default=0, nullable=False)
    platform_amount = Column(Numeric(10, 2), default=0, nullable=False)
    business_amount = Column(Numeric(10, 2), default=0, nullable=False)
    status = Column(String(20), default="pending", nullable=False, index=True)
    notes = Column(Text, nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
