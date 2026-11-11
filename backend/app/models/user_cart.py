from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, TimestampMixin


class UserCart(TimestampMixin, Base):
    __tablename__ = "user_carts"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload = Column(JSONB, nullable=False, default=list)
