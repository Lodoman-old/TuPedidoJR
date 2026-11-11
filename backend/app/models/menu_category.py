from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class MenuCategory(TimestampMixin, Base):
    __tablename__ = "menu_categories"

    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    name = Column(String(100), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
