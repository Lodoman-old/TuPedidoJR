from sqlalchemy import Boolean, Column, DECIMAL, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class RestaurantAdjustment(TimestampMixin, Base):
    __tablename__ = "restaurant_adjustments"

    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("delivery_incidents.id"), nullable=True)
    kind = Column(String(10), default="credit", nullable=False)
    amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    description = Column(Text, nullable=True)
    settled = Column(Boolean, default=False, nullable=False)
