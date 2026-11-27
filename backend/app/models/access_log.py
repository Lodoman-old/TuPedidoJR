from sqlalchemy import Column, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class AccessLog(TimestampMixin, Base):
    """Una visita a una pantalla del sistema, con IP y usuario."""

    __tablename__ = "access_logs"
    __table_args__ = (
        Index("ix_access_logs_created_at", "created_at"),
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ip = Column(String(64), nullable=True, index=True)
    role = Column(String(20), nullable=True, index=True)
    path = Column(String(300), nullable=False)
    screen = Column(String(120), nullable=True, index=True)
    user_agent = Column(String(300), nullable=True)
