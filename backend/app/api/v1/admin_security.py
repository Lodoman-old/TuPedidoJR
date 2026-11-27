"""Panel de seguridad: eventos, IPs bloqueadas y ajustes."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.access_log import AccessLog
from app.models.courier_sos import CourierSOS
from app.models.user import User
from app.services.audit_service import log_action
from app.services.audience_service import audience_overview
from app.services.security_service import (
    client_ip,
    is_valid_ip,
    list_security_overview,
    security_guard,
    truthy,
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
    sos_rows = (
        await db.execute(
            select(CourierSOS, User)
            .join(User, User.id == CourierSOS.user_id)
            .where(CourierSOS.status == "open")
            .order_by(CourierSOS.created_at.desc())
            .limit(20)
        )
    ).all()
    courier_sos = [
        {
            "id": str(sos.id),
            "courier": user.name or user.email,
            "phone": user.phone,
            "lat": sos.lat,
            "lng": sos.lng,
            "message": sos.message,
            "order_id": str(sos.order_id) if sos.order_id else None,
            "created_at": sos.created_at.isoformat() if sos.created_at else None,
        }
        for sos, user in sos_rows
    ]
    return {
        **data,
        "audience": await audience_overview(db),
        "courier_sos": courier_sos,
        "client_ip": client_ip(request, trust_cf=truthy(settings.get("trust_cf"))),
        "settings": {
            "enabled": truthy(settings.get("enabled")),
            "auto_block": truthy(settings.get("auto_block")),
            "rate_limit": settings.get("rate_limit") or "400",
            "block_minutes": settings.get("block_minutes") or "60",
            "whitelist": settings.get("whitelist") or "",
            "trust_cf": truthy(settings.get("trust_cf")),
            "email_mode": settings.get("email_mode") or "daily",
        },
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/security/access")
async def access_overview(
    days: int = Query(default=7, ge=1, le=90),
    ip: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=20, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Accesos por IP, usuario y pantalla para el administrador."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    filters = [AccessLog.created_at >= since]
    ip_filter = (ip or "").strip()
    if ip_filter:
        filters.append(AccessLog.ip == ip_filter)
    user_filter = (q or "").strip()
    pattern = f"%{user_filter}%"
    if user_filter:
        filters.append(
            or_(User.name.ilike(pattern), User.email.ilike(pattern))
        )

    def apply_join(stmt):
        return stmt.outerjoin(User, User.id == AccessLog.user_id)

    rows = (
        await db.execute(
            apply_join(
                select(AccessLog, User.name, User.email)
                .where(*filters)
                .order_by(AccessLog.created_at.desc())
                .limit(limit)
            )
        )
    ).all()

    visits = [
        {
            "id": str(row.AccessLog.id),
            "created_at": row.AccessLog.created_at.isoformat()
            if row.AccessLog.created_at
            else None,
            "user_id": str(row.AccessLog.user_id)
            if row.AccessLog.user_id
            else None,
            "user_name": row.name or "Usuario eliminado",
            "user_email": row.email,
            "role": row.AccessLog.role,
            "ip": row.AccessLog.ip,
            "screen": row.AccessLog.screen,
            "path": row.AccessLog.path,
            "user_agent": row.AccessLog.user_agent,
        }
        for row in rows
    ]

    totals_row = (
        await db.execute(
            apply_join(
                select(
                    func.count(AccessLog.id),
                    func.count(func.distinct(AccessLog.ip)),
                    func.count(func.distinct(AccessLog.user_id)),
                    func.count(func.distinct(AccessLog.screen)),
                ).where(*filters)
            )
        )
    ).one()

    last_24h = (
        await db.execute(
            apply_join(
                select(func.count(AccessLog.id)).where(
                    *filters, AccessLog.created_at >= now - timedelta(hours=24)
                )
            )
        )
    ).scalar_one() or 0

    ip_rows = (
        await db.execute(
            apply_join(
                select(
                    AccessLog.ip,
                    func.count(AccessLog.id),
                    func.count(func.distinct(AccessLog.user_id)),
                    func.min(AccessLog.created_at),
                    func.max(AccessLog.created_at),
                )
                .where(*filters)
                .group_by(AccessLog.ip)
                .order_by(func.max(AccessLog.created_at).desc())
                .limit(100)
            )
        )
    ).all()

    latest_by_ip: dict[str, dict] = {}
    for visit in visits:
        key = visit["ip"] or "desconocida"
        entry = latest_by_ip.setdefault(
            key,
            {"last_screen": None, "last_path": None, "user_names": []},
        )
        if entry["last_screen"] is None:
            entry["last_screen"] = visit["screen"]
            entry["last_path"] = visit["path"]
        name = visit["user_name"]
        if name and name not in entry["user_names"] and len(entry["user_names"]) < 5:
            entry["user_names"].append(name)

    ips = []
    for row in ip_rows:
        key = row[0] or "desconocida"
        extra = latest_by_ip.get(key, {})
        ips.append(
            {
                "ip": key,
                "visits": int(row[1] or 0),
                "users": int(row[2] or 0),
                "first_seen": row[3].isoformat() if row[3] else None,
                "last_seen": row[4].isoformat() if row[4] else None,
                "last_screen": extra.get("last_screen"),
                "last_path": extra.get("last_path"),
                "user_names": extra.get("user_names") or [],
            }
        )

    screen_rows = (
        await db.execute(
            apply_join(
                select(
                    AccessLog.screen,
                    AccessLog.path,
                    func.count(AccessLog.id),
                    func.count(func.distinct(AccessLog.user_id)),
                )
                .where(*filters)
                .group_by(AccessLog.screen, AccessLog.path)
                .order_by(func.count(AccessLog.id).desc())
                .limit(60)
            )
        )
    ).all()

    return {
        "days": days,
        "filters": {"ip": ip_filter or None, "q": user_filter or None},
        "totals": {
            "visits": int(totals_row[0] or 0),
            "ips": int(totals_row[1] or 0),
            "users": int(totals_row[2] or 0),
            "screens": int(totals_row[3] or 0),
            "last_24h": int(last_24h),
        },
        "ips": ips,
        "screens": [
            {
                "screen": row[0],
                "path": row[1],
                "visits": int(row[2] or 0),
                "users": int(row[3] or 0),
            }
            for row in screen_rows
        ],
        "visits": visits,
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

@router.post("/security/sos/{sos_id}/resolve")
async def resolve_courier_sos(
    sos_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    sos = await db.get(CourierSOS, sos_id)
    if not sos:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    sos.status = "resolved"
    sos.resolved_at = datetime.now(timezone.utc)
    sos.resolved_by = current_user.id
    await log_action(
        db, current_user.id, "security.sos_resolve", "courier_sos", str(sos.id), None
    )
    await db.commit()
    return {"ok": True}
