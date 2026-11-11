from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.services.email_service import send_password_reset
from app.services.order_service import get_setting_value

router = APIRouter()
_RESET_SALT = "tupedidojr-password-reset"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=_RESET_SALT)


def _fingerprint(password_hash: str) -> str:
    return password_hash[-16:]


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email ya registrado")

    referred_by = None
    if body.referral_code:
        ref_result = await db.execute(
            select(User).where(User.referral_code == body.referral_code.strip().upper())
        )
        referrer = ref_result.scalar_one_or_none()
        if not referrer:
            raise HTTPException(status_code=400, detail="Código de referido inválido")
        referred_by = referrer.id

    user = User(
        name=body.name,
        email=body.email,
        phone=body.phone,
        password_hash=hash_password(body.password),
        address=body.address,
        referral_code=uuid.uuid4().hex[:8].upper(),
        referred_by=referred_by,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return TokenResponse(access_token=token, expires_in=expires_in, is_superuser=user.is_superuser)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

    token = create_access_token(subject=str(user.id))
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return TokenResponse(access_token=token, expires_in=expires_in, is_superuser=user.is_superuser)


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if user and user.is_active:
        token = _serializer().dumps({
            "uid": str(user.id),
            "fp": _fingerprint(user.password_hash),
        })
        base_url = (
            await get_setting_value(db, "APP_PUBLIC_URL", str(request.base_url).rstrip("/"))
        ).rstrip("/")
        reset_url = f"{base_url}/web/reset-password?token={quote(token)}"
        await send_password_reset(db, user.email, user.name, reset_url)
    return {
        "message": "Si el correo está registrado, recibirás un enlace para restablecer la contraseña."
    }


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = _serializer().loads(body.token, max_age=86400)
    except SignatureExpired as exc:
        raise HTTPException(status_code=400, detail="El enlace venció. Solicita otro.") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="Enlace inválido") from exc

    try:
        user_id = uuid.UUID(payload.get("uid", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Enlace inválido") from exc
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Usuario no válido")
    if _fingerprint(user.password_hash) != payload.get("fp"):
        raise HTTPException(status_code=400, detail="El enlace ya fue utilizado")

    user.password_hash = hash_password(body.password)
    await db.commit()
    return {"message": "Contraseña actualizada. Ya puedes iniciar sesión."}
