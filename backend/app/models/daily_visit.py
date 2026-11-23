from sqlalchemy import Column, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class DailyVisit(TimestampMixin, Base):
    """Una fila por usuario y día, con el número de páginas vistas."""

    __tablename__ = "daily_visits"
    __table_args__ = (
        UniqueConstraint("visited_on", "user_id", name="uq_daily_visits_user_day"),
    )

    visited_on = Column(Date, nullable=False, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), default="customer", nullable=False, index=True)
    views = Column(Integer, default=1, nullable=False)
