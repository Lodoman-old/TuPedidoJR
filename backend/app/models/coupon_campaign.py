from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class CouponCampaign(TimestampMixin, Base):
    """Historial de campañas de cupón enviadas a los clientes de un negocio."""

    __tablename__ = "coupon_campaigns"

    coupon_id = Column(
        UUID(as_uuid=True),
        ForeignKey("coupons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    channels = Column(String(50), default="", nullable=False)
    audience_count = Column(Integer, default=0, nullable=False)
    push_sent = Column(Integer, default=0, nullable=False)
    push_failed = Column(Integer, default=0, nullable=False)
    email_sent = Column(Integer, default=0, nullable=False)
    email_failed = Column(Integer, default=0, nullable=False)
