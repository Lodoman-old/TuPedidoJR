from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.core.security import hash_password
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_user import RestaurantUser
from app.models.user import User

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class AdminUserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AdminUserUpdate(BaseModel):
    is_superuser: bool | None = None
    is_active: bool | None = None


@router.post("", status_code=201)
async def create_admin_user(
    body: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superuser),
):
    email = body.email.lower()
    exists = await db.execute(select(User).where(User.email == email))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ese correo ya está registrado")
    user = User(
        name=body.name.strip(),
        email=email,
        password_hash=hash_password(body.password),
        is_active=True,
        is_superuser=True,
        email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id), "name": user.name, "email": user.email}


@router.patch("/{user_id}")
async def update_admin_user(
    user_id: str,
    body: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    data = body.model_dump(exclude_unset=True)
    if str(user.id) == str(current_user.id):
        if data.get("is_superuser") is False:
            raise HTTPException(status_code=400, detail="No puedes quitarte permisos de administrador")
        if data.get("is_active") is False:
            raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta")
    for key, value in data.items():
        setattr(user, key, value)
    await db.commit()
    return {
        "id": str(user.id),
        "is_superuser": bool(user.is_superuser),
        "is_active": bool(user.is_active),
    }


@router.get("")
async def list_users(
    q: str | None = Query(default=None, max_length=120),
    role: str = Query(default="all"),
    status: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superuser),
):
    users = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()

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
            "business_type": restaurant.business_type or "restaurant",
            "role": "owner",
        })
    for row in staff_rows:
        restaurant = restaurants_by_id.get(str(row.restaurant_id))
        if not restaurant:
            continue
        businesses[str(row.user_id)].append({
            "id": str(restaurant.id),
            "name": restaurant.name,
            "business_type": restaurant.business_type or "restaurant",
            "role": row.role,
        })

    order_rows = await db.execute(
        select(
            Order.user_id,
            func.count(Order.id),
            func.max(Order.placed_at),
        ).group_by(Order.user_id)
    )
    orders = {
        str(user_id): {"count": int(count or 0), "last": last}
        for user_id, count, last in order_rows.all()
    }

    items = []
    summary = {
        "total": len(users),
        "clients": 0,
        "businesses": 0,
        "couriers": 0,
        "admins": 0,
        "active": 0,
    }
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
            summary["active"] += 1

        if role != "all" and role not in roles:
            continue
        if status == "active" and not user.is_active:
            continue
        if status == "inactive" and user.is_active:
            continue

        haystack = " ".join(filter(None, [user.name, user.email, user.phone])).lower()
        if q and q.strip().lower() not in haystack:
            continue

        courier = couriers.get(uid)
        stats = orders.get(uid, {"count": 0, "last": None})
        items.append({
            "id": uid,
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "address": user.address,
            "is_active": bool(user.is_active),
            "is_superuser": bool(user.is_superuser),
            "trusted_customer": bool(user.trusted_customer),
            "loyalty_points": int(user.loyalty_points or 0),
            "created_at": _iso(user.created_at),
            "roles": roles,
            "businesses": businesses.get(uid, []),
            "courier": {
                "vehicle_type": courier.vehicle_type,
                "is_available": bool(courier.is_available),
                "rating": float(courier.rating or 0),
                "total_deliveries": int(courier.total_deliveries or 0),
            } if courier else None,
            "orders_count": stats["count"],
            "last_order_at": _iso(stats["last"]),
        })

    total_filtered = len(items)
    start = (page - 1) * page_size
    return {
        "summary": summary,
        "total": total_filtered,
        "page": page,
        "page_size": page_size,
        "items": items[start:start + page_size],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
