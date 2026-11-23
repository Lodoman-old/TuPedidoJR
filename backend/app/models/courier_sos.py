from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class CourierSOS(TimestampMixin, Base):
    """Aviso de auxilio enviado por un repartidor."""

    __tablename__ = "courier_sos"

    courier_id = Column(
        UUID(as_uuid=True),
        ForeignKey("delivery_persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String(20), default="open", nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
