"""Presencia de usuarios: última actividad registrada.

La marca se actualiza como máximo una vez por minuto para no escribir en la
base en cada petición. La pantalla de administración clasifica a los usuarios
según ese dato.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

TOUCH_INTERVAL_SECONDS = 60
ONLINE_WINDOW_MINUTES = 5
RECENT_WINDOW_MINUTES = 60


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def touch_last_seen(
    db: AsyncSession, user: User, force: bool = False
) -> bool:
    """Registra la actividad del usuario si pasó el intervalo mínimo."""
    now = datetime.now(timezone.utc)
    last = _aware(user.last_seen_at)
    if (
        not force
        and last is not None
        and (now - last).total_seconds() < TOUCH_INTERVAL_SECONDS
    ):
        return False
    user.last_seen_at = now
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        return False
    return True


def presence_status(
    last_seen_at: datetime | None, now: datetime | None = None
) -> str:
    """Devuelve online, recent, offline o never."""
    last = _aware(last_seen_at)
    if last is None:
        return "never"
    current = now or datetime.now(timezone.utc)
    elapsed = (current - last).total_seconds()
    if elapsed <= ONLINE_WINDOW_MINUTES * 60:
        return "online"
    if elapsed <= RECENT_WINDOW_MINUTES * 60:
        return "recent"
    return "offline"


def minutes_since(
    last_seen_at: datetime | None, now: datetime | None = None
) -> int | None:
    last = _aware(last_seen_at)
    if last is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0, int((current - last).total_seconds() // 60))
