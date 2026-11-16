from __future__ import annotations

import json
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
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
    TwoFactorCodeRequest,
    TwoFactorDisableRequest,
    TwoFactorSetupOut,
    TwoFactorVerifyRequest,
    UserOut,
)
from app.services import totp_service
from app.services.email_service import send_password_reset
from app.services.order_service import get_setting_value
from app.services.security_service import security_guard

router = APIRouter()
_RESET_SALT = "tupedidojr-password-reset"
_2FA_SALT = "tupedidojr-2fa"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=_RESET_SALT)


def _fingerprint(password_hash: str) -> str:
    return password_hash[-16:]


def _twofa_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=_2FA_SALT)


def _token_response(user: User) -> TokenResponse:
    token = create_access_token(subject=str(user.id))
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        is_superuser=user.is_superuser,
    )


def _check_second_factor(user: User, code: str) -> tuple[bool, bool]:
    """Devuelve (válido, usó_código_de_recuperación)."""
    if totp_service.verify(user.totp_secret or "", code):
        return True, False
    hashed = totp_service.hash_code(code)
    try:
        saved = json.loads(user.totp_recovery_codes or "[]")
    except (TypeError, ValueError):
        saved = []
    if hashed in saved:
        saved.remove(hashed)
        user.totp_recovery_codes = json.dumps(saved)
        return True, True
    return False, False


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


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = str(body.email).strip().lower()
    wait = security_guard.account_locked_for(email)
    if wait > 0:
        minutes = max(1, wait // 60 + 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos para esta cuenta. Espera {minutes} minuto(s).",
        )

    result = await db.execute(select(User).where(User.email == str(body.email).strip()))
    user = result.scalar_one_or_none()
    if not user:
        result = await db.execute(select(User).where(func.lower(User.email) == email))
        user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        security_guard.register_account_failure(email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )
    security_guard.reset_account_failures(email)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

    if user.is_superuser and user.totp_enabled:
        return {
            "requires_2fa": True,
            "temp_token": _twofa_serializer().dumps({"uid": str(user.id)}),
        }

    return _token_response(user)


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


@router.get("/2fa/status")
async def twofa_status(current_user: User = Depends(get_current_user)):
    return {
        "enabled": bool(current_user.totp_enabled),
        "is_superuser": current_user.is_superuser,
    }


@router.post("/2fa/setup", response_model=TwoFactorSetupOut)
async def twofa_setup(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Solo administradores pueden activar el doble factor")
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=409,
            detail="El doble factor ya está activo. Desactívalo antes de generar una clave nueva.",
        )
    secret = totp_service.generate_secret()
    codes = totp_service.generate_recovery_codes()
    current_user.totp_secret = secret
    current_user.totp_recovery_codes = json.dumps([totp_service.hash_code(code) for code in codes])
    current_user.totp_enabled = False
    await db.commit()
    uri = totp_service.provisioning_uri(secret, current_user.email)
    qr_svg = ""
    try:
        import segno

        qr_svg = segno.make(uri, error="m").svg_inline(
            scale=5, border=2, dark="#0d1b2a", light="#ffffff"
        )
    except Exception:
        qr_svg = ""
    return TwoFactorSetupOut(
        secret=secret,
        otpauth_uri=uri,
        qr_svg=qr_svg,
        recovery_codes=codes,
    )


@router.post("/2fa/enable")
async def twofa_enable(
    body: TwoFactorCodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Solo administradores")
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Primero genera la clave de configuración")
    if not totp_service.verify(current_user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Código incorrecto. Revisa la hora de tu teléfono.")
    current_user.totp_enabled = True
    await db.commit()
    return {"ok": True}


@router.post("/2fa/verify", response_model=TokenResponse)
async def twofa_verify(
    body: TwoFactorVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = _twofa_serializer().loads(body.temp_token, max_age=600)
    except SignatureExpired as exc:
        raise HTTPException(status_code=401, detail="La verificación expiró. Vuelve a iniciar sesión.") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail="Verificación no válida") from exc

    try:
        user_id = uuid.UUID(payload.get("uid", ""))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Verificación no válida") from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active or not user.is_superuser or not user.totp_enabled:
        raise HTTPException(status_code=401, detail="Verificación no válida")

    valid, used_recovery = _check_second_factor(user, body.code)
    if not valid:
        raise HTTPException(status_code=401, detail="Código incorrecto")
    if used_recovery:
        await db.commit()
    return _token_response(user)


@router.post("/2fa/disable")
async def twofa_disable(
    body: TwoFactorDisableRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Solo administradores")
    if not verify_password(body.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Contraseña incorrecta")
    if current_user.totp_enabled:
        valid, _used = _check_second_factor(current_user, body.code or "")
        if not valid:
            raise HTTPException(
                status_code=400,
                detail="Escribe el código de tu autenticador (o uno de recuperación).",
            )
    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.totp_recovery_codes = None
    await db.commit()
    return {"ok": True}
