from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=True)
    password_hash = Column(String(255), nullable=False)
    address = Column(Text, nullable=True)
    location = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    trusted_customer = Column(Boolean, default=False, nullable=False)
    loyalty_points = Column(Integer, default=0, nullable=False)
    referral_code = Column(String(20), unique=True, nullable=True, index=True)
    referred_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    referral_bonus_awarded = Column(Boolean, default=False, nullable=False)
