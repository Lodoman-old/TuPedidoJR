from sqlalchemy import Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class RestaurantUser(TimestampMixin, Base):
    __tablename__ = "restaurant_users"

    restaurant_id = Column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role = Column(String(20), default="staff", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
