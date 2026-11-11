from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class Review(TimestampMixin, Base):
    __tablename__ = "reviews"

    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=True)
    delivery_person_id = Column(UUID(as_uuid=True), ForeignKey("delivery_persons.id"), nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
