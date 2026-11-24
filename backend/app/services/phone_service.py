"""Utilidades para normalizar y detectar teléfonos repetidos."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


def normalize_phone(value: str | None) -> str:
    """Devuelve los últimos 10 dígitos del teléfono."""
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) == 13 and digits.startswith("521"):
        digits = "52" + digits[3:]
    return digits[-10:] if len(digits) >= 10 else digits


async def phone_in_use(
    db: AsyncSession,
    phone: str | None,
    *,
    exclude_user_id=None,
) -> User | None:
    """Busca otra cuenta activa con el mismo teléfono normalizado."""
    normalized = normalize_phone(phone)
    if len(normalized) < 10:
        return None
    result = await db.execute(
        select(User).where(
            User.is_active.is_(True),
            User.phone.is_not(None),
        )
    )
    for user in result.scalars().all():
        if exclude_user_id is not None and user.id == exclude_user_id:
            continue
        if normalize_phone(user.phone) == normalized:
            return user
    return None
