"""Registro de eventos de seguridad e IPs bloqueadas."""

from app.db.base import Base, TimestampMixin
from sqlalchemy import Boolean, Column, DateTime, String, Text


class SecurityEvent(TimestampMixin, Base):
    __tablename__ = "security_events"

    ip = Column(String(64), nullable=False, index=True)
    kind = Column(String(40), nullable=False, index=True)
    path = Column(String(400), nullable=True)
    method = Column(String(10), nullable=True)
    user_agent = Column(String(400), nullable=True)
    detail = Column(Text, nullable=True)
    blocked = Column(Boolean, nullable=False, default=False)


class BlockedIP(TimestampMixin, Base):
    __tablename__ = "blocked_ips"

    ip = Column(String(64), nullable=False, unique=True, index=True)
    reason = Column(String(40), nullable=False, default="auto")
    detail = Column(Text, nullable=True)
    path = Column(String(400), nullable=True)
    auto = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
