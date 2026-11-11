from sqlalchemy import Boolean, Column, DECIMAL, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class DeliveryPerson(TimestampMixin, Base):
    __tablename__ = "delivery_persons"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    vehicle_type = Column(String(20), nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)
    current_location = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    current_order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", use_alter=True, name="fk_dp_current_order"), nullable=True)
    rating = Column(DECIMAL(2, 1), default=0.0, nullable=False)
    total_deliveries = Column(Integer, default=0, nullable=False)

    payout_method = Column(String(10), default="cash", nullable=False)
    payout_frequency_days = Column(Integer, default=3, nullable=False)
    bank_name = Column(String(100), nullable=True)
    bank_account_holder = Column(String(150), nullable=True)
    bank_clabe = Column(String(18), nullable=True)
    is_mandadero = Column(Boolean, default=False, nullable=False)
    pending_platform_debt = Column(DECIMAL(10, 2), default=0, nullable=False)
    delivery_bonus_per_order = Column(DECIMAL(10, 2), default=0, nullable=False)
