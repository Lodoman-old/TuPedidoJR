"""Live operations dashboard for the superuser."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.cash_advance import CashAdvance
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
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
