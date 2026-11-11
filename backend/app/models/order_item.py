from sqlalchemy import Column, DECIMAL, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"

    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False)
    name = Column(String(150), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(DECIMAL(10, 2), nullable=False)
    subtotal = Column(DECIMAL(10, 2), nullable=False)
    notes = Column(Text, nullable=True)

    options = relationship(
        "OrderItemOption",
        backref="order_item",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
