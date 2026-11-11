from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, DECIMAL, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

from app.db.base import Base


class DeliveryLocation(Base):
    __tablename__ = "delivery_locations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    delivery_person_id = Column(UUID(as_uuid=True), ForeignKey("delivery_persons.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    speed_kmh = Column(DECIMAL(5, 1), nullable=True)
