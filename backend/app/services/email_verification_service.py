"""Verificación de correo: tokens firmados y envío del enlace."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.services.email_service import email_config, send_email_verification

_SALT = "tupedidojr-email-verify"
_MAX_AGE = 3 * 24 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=_SALT)


def make_token(user: User) -> str:
    return _serializer().dumps({"uid": str(user.id), "email": user.email})


def read_token(token: str) -> dict:
    """Devuelve {"uid", "email"} o lanza BadSignature/SignatureExpired."""
    return _serializer().loads(token, max_age=_MAX_AGE)


async def send_verification(db: AsyncSession, user: User) -> tuple[bool, str]:
    if user.email_verified:
        return True, "El correo ya está verificado"
    config = await email_config(db)
    url = f"{config['public_url']}/web/verify-email?token={make_token(user)}"
    return await send_email_verification(db, user.email, user.name, url)


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
    if not user or (user.email or "").lower() != str(data.get("email") or "").lower():
        return None
    if not user.email_verified:
        user.email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)
    return user
