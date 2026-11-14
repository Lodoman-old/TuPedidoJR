from sqlalchemy import Column, DateTime, DECIMAL, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class StoreRequest(TimestampMixin, Base):
    __tablename__ = "store_requests"

    store_id = Column(
        UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    reference_photo_url = Column(Text, nullable=True)
    budget = Column(DECIMAL(10, 2), nullable=True)
    status = Column(String(20), default="pending", nullable=False)
    quoted_price = Column(DECIMAL(10, 2), nullable=True)
    store_notes = Column(Text, nullable=True)
    delivery_address = Column(Text, nullable=False)
    delivery_location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    payment_method = Column(String(10), default="cash", nullable=False)
    notes = Column(Text, nullable=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
