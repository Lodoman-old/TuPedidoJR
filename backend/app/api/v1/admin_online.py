"""Usuarios en línea y última actividad registrada."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.restaurant import Restaurant
from app.models.restaurant_user import RestaurantUser
from app.models.user import User
from app.services.presence_service import (
    ONLINE_WINDOW_MINUTES,
    RECENT_WINDOW_MINUTES,
    minutes_since,
    presence_status,
)

router = APIRouter()

STATUS_LABELS = {
    "online": "En línea",
    "recent": "Hace poco",
    "offline": "Inactivo",
    "never": "Sin actividad",
}
ROLE_LABELS = {
    "admin": "Administrador",
    "negocio": "Negocio",
    "repartidor": "Repartidor",
    "cliente": "Cliente",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _matches_status(presence: str, status: str) -> bool:
    if status == "all":
        return True
    if status == "offline":
        return presence in ("offline", "never")
    return presence == status


@router.get("/online-users")
async def list_online_users(
    status: str = Query(default="all"),
    role: str = Query(default="all"),
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superuser),
):
    users = (
        await db.execute(select(User).order_by(User.last_seen_at.desc().nulls_last()))
    ).scalars().all()

    couriers = {
        str(row.user_id): row
        for row in (await db.execute(select(DeliveryPerson))).scalars().all()
    }
    restaurants = (await db.execute(select(Restaurant))).scalars().all()
    restaurants_by_id = {str(r.id): r for r in restaurants}
    staff_rows = (await db.execute(select(RestaurantUser))).scalars().all()

    businesses = defaultdict(list)
    for restaurant in restaurants:
        businesses[str(restaurant.owner_id)].append({
            "id": str(restaurant.id),
            "name": restaurant.name,
            "role": "owner",
        })
    for row in staff_rows:
        restaurant = restaurants_by_id.get(str(row.restaurant_id))
        if not restaurant:
            continue
        businesses[str(row.user_id)].append({
            "id": str(restaurant.id),
            "name": restaurant.name,
            "role": row.role,
        })

    now = datetime.now(timezone.utc)
    summary = {
        "total": len(users),
        "online": 0,
        "recent": 0,
        "offline": 0,
        "never": 0,
        "active_accounts": 0,
        "suspended_accounts": 0,
        "clients": 0,
        "businesses": 0,
        "couriers": 0,
        "admins": 0,
    }

    items = []
    for user in users:
        uid = str(user.id)
        roles = []
        if user.is_superuser:
            roles.append("admin")
            summary["admins"] += 1
        if uid in couriers:
            roles.append("repartidor")
            summary["couriers"] += 1
        if uid in businesses:
            roles.append("negocio")
            summary["businesses"] += 1
        if not roles:
            roles.append("cliente")
            summary["clients"] += 1

        if user.is_active:
            summary["active_accounts"] += 1
        else:
            summary["suspended_accounts"] += 1

        presence = presence_status(user.last_seen_at, now)
        summary[presence] += 1

        if not _matches_status(presence, status):
            continue
        if role != "all" and role not in roles:
            continue

        haystack = " ".join(filter(None, [user.name, user.email, user.phone])).lower()
        if q and q.strip().lower() not in haystack:
            continue

        courier = couriers.get(uid)
        items.append({
            "id": uid,
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "roles": roles,
            "role_labels": [ROLE_LABELS[r] for r in roles],
            "businesses": businesses.get(uid, []),
            "is_active": bool(user.is_active),
            "last_seen_at": _iso(user.last_seen_at),
            "minutes_ago": minutes_since(user.last_seen_at, now),
            "presence": presence,
            "presence_label": STATUS_LABELS[presence],
            "courier": {
                "is_available": bool(courier.is_available),
                "vehicle_type": courier.vehicle_type,
            } if courier else None,
            "created_at": _iso(user.created_at),
        })

    total_filtered = len(items)
    start = (page - 1) * page_size
    return {
        "summary": summary,
        "online_window_minutes": ONLINE_WINDOW_MINUTES,
        "recent_window_minutes": RECENT_WINDOW_MINUTES,
        "total": total_filtered,
        "page": page,
        "page_size": page_size,
        "items": items[start:start + page_size],
        "generated_at": now.isoformat(),
    }
