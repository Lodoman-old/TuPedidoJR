from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class Appointment(TimestampMixin, Base):
    """Cita de un servicio (barbería, salón, consultorio)."""

    __tablename__ = "appointments"

    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_id = Column(
        UUID(as_uuid=True),
        ForeignKey("business_services.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    staff_id = Column(
        UUID(as_uuid=True),
        ForeignKey("business_staff.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    client_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    client_name = Column(String(120), nullable=False)
    client_phone = Column(String(25), nullable=True)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), default="confirmed", nullable=False, index=True)
    price = Column(Numeric(10, 2), default=0, nullable=False)
    payment_mode = Column(String(20), default="cash", nullable=False)
    payment_status = Column(String(20), default="cash_pending", nullable=False)
    deposit_amount = Column(Numeric(10, 2), default=0, nullable=False)
    platform_fee = Column(Numeric(10, 2), default=0, nullable=False)
    business_fee = Column(Numeric(10, 2), default=0, nullable=False)
    proof_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
