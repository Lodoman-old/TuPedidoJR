"""Verificación de teléfono con enlace firmado.

El enlace se envía manualmente por WhatsApp desde el panel de administración.
El token vence en 24 horas y solo es válido para el teléfono con el que se
generó.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.services.order_service import get_setting_value

_SALT = "tupedidojr-phone-verify"
_MAX_AGE = 24 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=_SALT)


def make_token(user: User) -> str:
    return _serializer().dumps(
        {"uid": str(user.id), "phone": (user.phone or "").strip()}
    )


def read_token(token: str) -> dict:
    """Devuelve {"uid", "phone"} o lanza BadSignature/SignatureExpired."""
    return _serializer().loads(token, max_age=_MAX_AGE)


async def make_link(db: AsyncSession, user: User) -> str:
    base = (await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)).rstrip("/")
    return f"{base}/web/verify-phone?token={make_token(user)}"


async def verify(db: AsyncSession, token: str) -> User | None:
    try:
        data = read_token(token)
    except (BadSignature, SignatureExpired):
        return None
    try:
        uid = uuid.UUID(str(data.get("uid")))
    except (ValueError, AttributeError, TypeError):
        return None
    user = await db.get(User, uid)
    if not user:
        return None
    phone = str(data.get("phone") or "").strip()
    if not phone or phone != (user.phone or "").strip():
        return None
    if not user.phone_verified:
        user.phone_verified = True
        user.phone_verified_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)
    return user
