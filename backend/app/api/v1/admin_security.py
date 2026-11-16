"""Panel de seguridad: eventos, IPs bloqueadas y ajustes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.user import User
from app.services.audit_service import log_action
from app.services.security_service import (
    client_ip,
    is_valid_ip,
    list_security_overview,
    security_guard,
)

router = APIRouter()


class BlockRequest(BaseModel):
    ip: str = Field(..., min_length=3, max_length=64)
    minutes: float = Field(default=60, ge=1, le=10080)
    reason: str | None = Field(default=None, max_length=40)


class UnblockRequest(BaseModel):
    ip: str = Field(..., min_length=3, max_length=64)


@router.get("/security/overview")
async def security_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    data = await list_security_overview(db)
    settings = await security_guard.refresh_settings(force=True)
    return {
        **data,
        "client_ip": client_ip(request),
        "settings": {
            "enabled": str(settings.get("enabled")).lower() in {"1", "true", "yes", "si", "sí", "on"},
            "auto_block": str(settings.get("auto_block")).lower() in {"1", "true", "yes", "si", "sí", "on"},
            "rate_limit": settings.get("rate_limit") or "400",
            "block_minutes": settings.get("block_minutes") or "60",
            "whitelist": settings.get("whitelist") or "",
        },
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/security/block")
async def security_block(
    body: BlockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    ip = body.ip.strip()
    if not is_valid_ip(ip):
        raise HTTPException(status_code=400, detail="Escribe una dirección IP válida")
    await security_guard.block(
        ip,
        body.minutes,
        body.reason or "manual",
        detail=f"Bloqueo manual por {current_user.email}",
        auto=False,
    )
    await log_action(db, current_user.id, "security.block", "ip", ip, {"minutes": body.minutes})
    await db.commit()
    return {"ok": True, "ip": ip, "minutes": body.minutes}


@router.post("/security/unblock")
async def security_unblock(
    body: UnblockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    ip = body.ip.strip()
    if not is_valid_ip(ip):
        raise HTTPException(status_code=400, detail="Escribe una dirección IP válida")
    await security_guard.unblock(ip, detail=f"Desbloqueo manual por {current_user.email}")
    await log_action(db, current_user.id, "security.unblock", "ip", ip, None)
    await db.commit()
    return {"ok": True, "ip": ip}


@router.post("/security/refresh")
async def security_refresh(
    current_user: User = Depends(require_superuser),
):
    security_guard.reset_settings_cache()
    await security_guard._refresh_settings(force=True)
    return {"ok": True}
