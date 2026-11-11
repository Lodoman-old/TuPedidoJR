from sqlalchemy import Boolean, Column, DECIMAL, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class MenuItem(TimestampMixin, Base):
    __tablename__ = "menu_items"

    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("menu_categories.id"), nullable=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(DECIMAL(10, 2), nullable=False)
    image_url = Column(Text, nullable=True)
    is_available = Column(Boolean, default=True, nullable=False)
    preparation_time_min = Column(Integer, nullable=True)

    option_groups = relationship(
        "MenuOptionGroup",
        back_populates="menu_item",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="MenuOptionGroup.sort_order",
    )
