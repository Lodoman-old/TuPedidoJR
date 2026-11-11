from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class PushToken(TimestampMixin, Base):
    """FCM registration token for a user's device (APK or PWA)."""

    __tablename__ = "push_tokens"
    __table_args__ = (UniqueConstraint("token", name="uq_push_tokens_token"),)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token = Column(String(512), nullable=False)
    platform = Column(String(20), nullable=False, default="web")  # web | android | ios
    device_label = Column(String(150), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_seen_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
