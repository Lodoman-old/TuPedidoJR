from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, TimestampMixin


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(100), nullable=False)
    entity = Column(String(50), nullable=True)
    entity_id = Column(String(100), nullable=True)
    detail = Column(JSONB, nullable=True)
