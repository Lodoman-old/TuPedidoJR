from sqlalchemy import Boolean, Column, Date, DECIMAL, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class Restaurant(TimestampMixin, Base):
    __tablename__ = "restaurants"

    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    cuisine = Column(String(100), nullable=True)
    slug = Column(String(120), unique=True, nullable=True, index=True)
    delivery_mode = Column(String(20), default="platform", nullable=False)
    pickup_enabled = Column(Boolean, default=False, nullable=False)
    status = Column(String(20), default="active", nullable=False)
    rejection_reason = Column(Text, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    public_page_enabled = Column(Boolean, default=True, nullable=False)
    location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    address = Column(Text, nullable=False)
    phone = Column(String(20), nullable=True)
    logo_url = Column(Text, nullable=True)
    is_open = Column(Boolean, default=True, nullable=False)
    rating = Column(DECIMAL(2, 1), default=0.0, nullable=False)
    delivery_radius_m = Column(Integer, default=3000, nullable=False)
    delivery_fee = Column(DECIMAL(10, 2), default=0.0, nullable=False)
    preparation_base_time_min = Column(Integer, default=10, nullable=False)

    commission_percentage = Column(DECIMAL(4, 1), nullable=True)
    commission_mode = Column(String(20), default="percentage", nullable=False)
    fixed_fee = Column(DECIMAL(10, 2), nullable=True)
    reservations_enabled = Column(Boolean, default=True, nullable=False)
    reservation_deposit_percent = Column(DECIMAL(5, 2), default=20, nullable=False)
    reservation_min_advance_min = Column(Integer, default=120, nullable=False)
    reservation_late_tolerance_min = Column(Integer, default=60, nullable=False)
    affiliation_expires_at = Column(Date, nullable=True)
    affiliation_reminder_on = Column(Date, nullable=True)
    payout_frequency_days = Column(Integer, default=7, nullable=False)
    bank_name = Column(String(100), nullable=True)
    bank_account_holder = Column(String(150), nullable=True)
    bank_clabe = Column(String(18), nullable=True)

    categories = relationship("MenuCategory", backref="restaurant", lazy="selectin")
    menu = relationship("MenuItem", backref="restaurant", lazy="selectin")
