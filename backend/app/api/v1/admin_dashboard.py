"""Live operations dashboard for the superuser."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.core.security import hash_password
from app.db.session import get_db
from app.models.cash_advance import CashAdvance
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.audit_service import log_action
from app.services.schedule_service import get_timezone, open_state_map

router = APIRouter()

ACTIVE_STATUSES = ["pending", "confirmed", "awaiting_courier", "preparing", "ready", "in_delivery", "picked_up"]
STATUS_LABELS = {
    "pending": "Pendiente",
    "confirmed": "Confirmado",
    "awaiting_courier": "Esperando repartidor",
    "preparing": "Preparando",
    "ready": "Listo",
    "in_delivery": "En reparto",
    "picked_up": "Recogido",
    "delivered": "Entregado",
    "cancelled": "Cancelado",
}


def _money(value) -> str:
    return f"{float(value or 0):.2f}"


@router.get("/delivery-radius")
async def delivery_radius(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    from app.services.order_service import get_setting_value

    raw = await get_setting_value(db, "DELIVERY_FREE_RADIUS_KM", "6")
    try:
        radius_m = int(float(raw) * 1000)
    except (TypeError, ValueError):
        radius_m = 6000

    rows = await db.execute(
        text("""
            SELECT id, name, ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
            FROM restaurants
            WHERE status = 'active' AND location IS NOT NULL
            ORDER BY name
        """)
    )
    centers = [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "lat": float(row["lat"]),
            "lng": float(row["lng"]),
        }
        for row in rows.mappings().all()
    ]
    return {"radius_m": radius_m, "centers": centers}


@router.get("/couriers/locations")
async def courier_locations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        text("""
            SELECT
                dp.id, u.name, u.email, u.phone,
                dp.is_available, dp.current_order_id,
                dp.vehicle_type, dp.payout_method,
                dp.bank_name, dp.bank_account_holder, dp.bank_clabe,
                dp.is_mandadero, dp.delivery_bonus_per_order,
                dp.rating, dp.total_deliveries, dp.pending_platform_debt,
                ST_Y(dp.current_location::geometry) AS lat,
                ST_X(dp.current_location::geometry) AS lng,
                dp.updated_at
            FROM delivery_persons dp
            JOIN users u ON u.id = dp.user_id
            ORDER BY u.name
        """)
    )
    rows = []
    for row in result.mappings().all():
        rows.append({
            "id": str(row["id"]),
            "name": row["name"] or row["email"],
            "email": row["email"],
            "phone": row["phone"],
            "is_available": bool(row["is_available"]),
            "current_order_id": str(row["current_order_id"]) if row["current_order_id"] else None,
            "vehicle_type": row["vehicle_type"],
            "payout_method": row["payout_method"],
            "bank_name": row["bank_name"],
            "bank_account_holder": row["bank_account_holder"],
            "bank_clabe": row["bank_clabe"],
            "is_mandadero": bool(row["is_mandadero"]),
            "delivery_bonus_per_order": str(row["delivery_bonus_per_order"] or 0),
            "rating": str(row["rating"] or 0),
            "total_deliveries": int(row["total_deliveries"] or 0),
            "pending_platform_debt": str(row["pending_platform_debt"] or 0),
            "lat": float(row["lat"]) if row["lat"] is not None else None,
            "lng": float(row["lng"]) if row["lng"] is not None else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        })
    return rows


@router.get("/dashboard")
async def admin_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    tz = await get_timezone(db)
    now = datetime.now(tz)
    start_today = datetime.combine(now.date(), time.min, tzinfo=tz).astimezone(timezone.utc)

    active_result = await db.execute(
        select(Order.status, func.count(Order.id))
        .where(Order.status.in_(ACTIVE_STATUSES))
        .group_by(Order.status)
    )
    by_status = {status: int(count) for status, count in active_result.all()}
    active_total = sum(by_status.values())

    today_result = await db.execute(
        select(Order).where(Order.placed_at >= start_today)
    )
    today_orders = list(today_result.scalars().all())
    delivered_today = [o for o in today_orders if o.status == "delivered"]
    today_sales = sum((o.total or Decimal("0")) for o in delivered_today)
    today_subtotal = sum((o.subtotal or Decimal("0")) for o in delivered_today)
    today_commission = sum((o.platform_commission or Decimal("0")) for o in delivered_today)
    today_tips = sum((o.tip_amount or Decimal("0")) for o in delivered_today)

    restaurants_result = await db.execute(select(Restaurant))
    restaurants = list(restaurants_result.scalars().all())
    states = await open_state_map(db, [r.id for r in restaurants])
    open_restaurants = 0
    for restaurant in restaurants:
        state = states.get(restaurant.id)
        if state and state["has_schedule"] and restaurant.is_open:
            open_restaurants += 1 if state["is_open_now"] else 0
        elif restaurant.is_open:
            open_restaurants += 1

    couriers_result = await db.execute(select(DeliveryPerson))
    couriers = list(couriers_result.scalars().all())
    available_couriers = sum(1 for c in couriers if c.is_available)

    transfers_result = await db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
        .where(
            Order.payment_method == "transfer",
            Order.payment_status.in_(["pending", "in_process"]),
            Order.status != "cancelled",
        )
    )
    transfers_count, transfers_amount = transfers_result.one()

    advances_result = await db.execute(
        select(func.count(CashAdvance.id), func.coalesce(func.sum(CashAdvance.amount), 0))
        .where(CashAdvance.status == "pending")
    )
    advances_count, advances_amount = advances_result.one()

    now_utc = datetime.now(timezone.utc)
    pending_alert_result = await db.execute(
        select(Order)
        .where(
            Order.status == "pending",
            Order.placed_at < now_utc - timedelta(minutes=10),
        )
        .order_by(Order.placed_at.asc())
        .limit(20)
    )
    late_preparing_result = await db.execute(
        select(Order)
        .where(
            Order.status.in_(["preparing", "ready"]),
            Order.placed_at < now_utc - timedelta(minutes=45),
        )
        .order_by(Order.placed_at.asc())
        .limit(20)
    )

    def _alert(order: Order) -> dict:
        return {
            "id": str(order.id),
            "status": order.status,
            "status_label": STATUS_LABELS.get(order.status, order.status),
            "total": _money(order.total),
            "placed_at": order.placed_at.isoformat() if order.placed_at else None,
            "minutes": int((now_utc - order.placed_at).total_seconds() // 60) if order.placed_at else 0,
        }

    recent_result = await db.execute(
        select(Order).order_by(Order.placed_at.desc()).limit(15)
    )
    recent_orders = [
        {
            "id": str(o.id),
            "status": o.status,
            "status_label": STATUS_LABELS.get(o.status, o.status),
            "total": _money(o.total),
            "payment_method": o.payment_method,
            "placed_at": o.placed_at.isoformat() if o.placed_at else None,
            "scheduled_for": o.scheduled_for.isoformat() if o.scheduled_for else None,
        }
        for o in recent_result.scalars().all()
    ]

    return {
        "now": now.isoformat(),
        "active": {
            "total": active_total,
            "by_status": [
                {"status": status, "label": STATUS_LABELS.get(status, status), "count": by_status.get(status, 0)}
                for status in ACTIVE_STATUSES
            ],
        },
        "today": {
            "orders": len(today_orders),
            "delivered": len(delivered_today),
            "sales": _money(today_sales),
            "subtotal": _money(today_subtotal),
            "commission": _money(today_commission),
            "tips": _money(today_tips),
        },
        "restaurants": {
            "total": len(restaurants),
            "open": open_restaurants,
        },
        "couriers": {
            "total": len(couriers),
            "available": available_couriers,
        },
        "transfers": {
            "count": int(transfers_count or 0),
            "amount": _money(transfers_amount),
        },
        "advances": {
            "count": int(advances_count or 0),
            "amount": _money(advances_amount),
        },
        "alerts": {
            "pending_10min": [_alert(o) for o in pending_alert_result.scalars().all()],
            "late_preparing": [_alert(o) for o in late_preparing_result.scalars().all()],
        },
        "recent_orders": recent_orders,
    }

class CourierCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(..., min_length=6, max_length=128)
    vehicle_type: str = Field(default="motorcycle", pattern="^(bike|motorcycle|car)$")
    payout_method: str = Field(default="cash", pattern="^(cash|transfer)$")
    bank_name: str | None = Field(default=None, max_length=100)
    bank_account_holder: str | None = Field(default=None, max_length=150)
    bank_clabe: str | None = Field(default=None, max_length=30)
    is_mandadero: bool = False
    delivery_bonus_per_order: Decimal = Decimal("0")


@router.post("/couriers", status_code=201)
async def create_courier(
    body: CourierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    existing = await db.scalar(
        select(User).where(func.lower(User.email) == body.email.strip().lower())
    )
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese correo")

    clabe = "".join(ch for ch in (body.bank_clabe or "") if ch.isdigit())
    if body.payout_method == "transfer":
        if not (body.bank_name or "").strip() or not (body.bank_account_holder or "").strip():
            raise HTTPException(
                status_code=400,
                detail="Para pago por transferencia indica banco y titular",
            )
        if len(clabe) != 18:
            raise HTTPException(status_code=400, detail="La CLABE debe tener 18 dígitos")

    user = User(
        name=body.name.strip(),
        email=body.email.strip().lower(),
        phone=(body.phone or "").strip() or None,
        password_hash=hash_password(body.password),
        referral_code=uuid.uuid4().hex[:8].upper(),
    )
    db.add(user)
    await db.flush()

    courier = DeliveryPerson(
        user_id=user.id,
        vehicle_type=body.vehicle_type,
        is_available=True,
        payout_method=body.payout_method,
        bank_name=(body.bank_name or "").strip() or None,
        bank_account_holder=(body.bank_account_holder or "").strip() or None,
        bank_clabe=clabe or None,
        is_mandadero=body.is_mandadero,
        delivery_bonus_per_order=body.delivery_bonus_per_order or Decimal("0"),
    )
    db.add(courier)
    await db.flush()
    await log_action(
        db, current_user.id, "courier.create", "delivery_person", courier.id,
        {"name": user.name, "email": user.email},
    )
    await db.commit()
    await db.refresh(courier)
    return {
        "id": str(courier.id),
        "user_id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "vehicle_type": courier.vehicle_type,
    }
