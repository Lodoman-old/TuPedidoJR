from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, DECIMAL, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class Mandado(TimestampMixin, Base):
    __tablename__ = "mandados"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    delivery_person_id = Column(UUID(as_uuid=True), ForeignKey("delivery_persons.id"), nullable=True)
    description = Column(Text, nullable=False)
    estimated_budget = Column(DECIMAL(10, 2), nullable=False)
    product_total = Column(DECIMAL(10, 2), nullable=True)
    delivery_fee = Column(DECIMAL(10, 2), default=0, nullable=False)
    risk_fee = Column(DECIMAL(10, 2), default=0, nullable=False)
    platform_fee = Column(DECIMAL(10, 2), default=10, nullable=False)
    estimated_total = Column(DECIMAL(10, 2), nullable=False)
    final_total = Column(DECIMAL(10, 2), nullable=True)
    payment_method = Column(String(10), default="cash", nullable=False)
    payment_status = Column(String(15), default="pending", nullable=False)
    prepayment_required = Column(Boolean, default=False, nullable=False)
    prepayment_proof_url = Column(Text, nullable=True)
    prepayment_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="pending", nullable=False)
    delivery_address = Column(Text, nullable=False)
    delivery_location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    receipt_photo_url = Column(Text, nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    purchased_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
