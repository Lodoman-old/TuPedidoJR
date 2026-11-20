from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class RentalBooking(TimestampMixin, Base):
    """Reserva de renta con uno o varios artículos."""

    __tablename__ = "rental_bookings"

    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
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
    address = Column(Text, nullable=True)
    location = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    status = Column(String(20), default="confirmed", nullable=False, index=True)
    payment_mode = Column(String(20), default="cash", nullable=False)
    payment_status = Column(String(20), default="cash_pending", nullable=False)
    deposit_amount = Column(Numeric(10, 2), default=0, nullable=False)
    deposit_percent = Column(Numeric(5, 2), default=0, nullable=False)
    online_amount = Column(Numeric(10, 2), default=0, nullable=False)
    cash_due = Column(Numeric(10, 2), default=0, nullable=False)
    business_credit = Column(Numeric(10, 2), default=0, nullable=False)
    business_debt = Column(Numeric(10, 2), default=0, nullable=False)
    platform_fee = Column(Numeric(10, 2), default=0, nullable=False)
    business_fee = Column(Numeric(10, 2), default=0, nullable=False)
    proof_url = Column(Text, nullable=True)
    receipt_status = Column(String(20), default="none", nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    refund_amount = Column(Numeric(10, 2), default=0, nullable=False)
    client_reminder_sent_at = Column(DateTime(timezone=True), nullable=True)
    business_reminder_sent_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    items = relationship(
        "RentalBookingItem",
        backref="booking",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class RentalBookingItem(TimestampMixin, Base):
    __tablename__ = "rental_booking_items"

    booking_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rental_bookings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_id = Column(
        UUID(as_uuid=True),
        ForeignKey("business_services.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(String(120), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), default=0, nullable=False)
    duration_min = Column(Integer, default=60, nullable=False)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    subtotal = Column(Numeric(10, 2), default=0, nullable=False)
