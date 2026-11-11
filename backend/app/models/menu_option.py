from sqlalchemy import Boolean, Column, DECIMAL, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class MenuOptionGroup(TimestampMixin, Base):
    __tablename__ = "menu_option_groups"

    menu_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    selection_type = Column(String(10), default="single", nullable=False)
    pricing_mode = Column(String(20), default="delta", nullable=False)
    is_required = Column(Boolean, default=False, nullable=False)
    min_selections = Column(Integer, default=0, nullable=False)
    max_selections = Column(Integer, default=1, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    options = relationship(
        "MenuOption",
        back_populates="group",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="MenuOption.sort_order",
    )
    menu_item = relationship("MenuItem", back_populates="option_groups")


class MenuOption(TimestampMixin, Base):
    __tablename__ = "menu_options"

    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("menu_option_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    price_delta = Column(DECIMAL(10, 2), default=0, nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    group = relationship("MenuOptionGroup", back_populates="options")
