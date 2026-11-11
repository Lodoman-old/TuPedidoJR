import uuid

from sqlalchemy import Column, DECIMAL, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class OrderItemOption(Base):
    __tablename__ = "order_item_options"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    option_id = Column(UUID(as_uuid=True), ForeignKey("menu_options.id"), nullable=True)
    group_name = Column(String(100), nullable=False)
    name = Column(String(100), nullable=False)
    price_delta = Column(DECIMAL(10, 2), default=0, nullable=False)
    portion = Column(DECIMAL(6, 4), default=1.0, nullable=False)
