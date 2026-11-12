"""Business reports and CSV exports.

Access rules:
* Superuser: sees every restaurant. Can filter by ``restaurant_id``.
* Restaurant owner: sees only their own restaurants.
"""
import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.services.restaurant_access import FINANCE_ROLES, have_role, my_restaurants
from app.models.delivery_payout import DeliveryPayout
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_payout import RestaurantPayout
from app.models.user import User
from app.services.schedule_service import get_timezone

router = APIRouter()

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
PAYMENT_METHOD_LABELS = {
    "cash": "Efectivo",
    "mp": "Mercado Pago",
    "transfer": "Transferencia",
}
PAYMENT_STATUS_LABELS = {
    "pending": "Pendiente",
    "approved": "Aprobado",
    "in_process": "En proceso",
    "rejected": "Rechazado",
    "refunded": "Reembolsado",
    "cancelled": "Cancelado",
    "paid": "Pagado",
}
REFUND_STATUS_LABELS = {
    "none": "Sin reembolso",
    "not_required": "No requiere",
    "pending": "Pendiente",
    "refunded": "Reembolsado",
}


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


async def _scope(
    db: AsyncSession,
    current_user: User,
    restaurant_id: str | None,
) -> tuple[list | None, Restaurant | None]:
    """Return ``(restaurant_ids, single_restaurant)`` for the query scope."""
    if current_user.is_superuser:
        if restaurant_id:
            result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
            restaurant = result.scalar_one_or_none()
            if not restaurant:
                raise HTTPException(status_code=404, detail="Restaurante no encontrado")
            return [restaurant.id], restaurant
        return None, None

    owned = await my_restaurants(db, current_user)
    owned = [
        r for r in owned
        if await have_role(db, r.id, current_user, FINANCE_ROLES)
    ]
    if not owned:
        raise HTTPException(status_code=403, detail="No tienes restaurantes registrados")
    if restaurant_id:
        match = next((r for r in owned if str(r.id) == str(restaurant_id)), None)
        if not match:
            raise HTTPException(status_code=403, detail="No tienes acceso a este restaurante")
        return [match.id], match
    return [r.id for r in owned], None


async def _date_range(
    db: AsyncSession,
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime, datetime, date, date]:
    today = date.today()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="La fecha inicial no puede ser mayor a la final")

    tz = await get_timezone(db)
    start = datetime.combine(date_from, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, end, date_from, date_to


async def _load_orders(
    db: AsyncSession,
    start: datetime,
    end: datetime,
    restaurant_ids: list | None,
) -> list[Order]:
    stmt = select(Order).where(Order.placed_at >= start, Order.placed_at < end)
    if restaurant_ids:
        stmt = stmt.where(Order.restaurant_id.in_(restaurant_ids))
    stmt = stmt.order_by(Order.placed_at.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _names(db: AsyncSession, orders: list[Order]) -> tuple[dict, dict]:
    restaurant_ids = list({o.restaurant_id for o in orders})
    user_ids = list({o.user_id for o in orders})

    restaurants = {}
    if restaurant_ids:
        result = await db.execute(
            select(Restaurant.id, Restaurant.name).where(Restaurant.id.in_(restaurant_ids))
        )
        restaurants = {str(row[0]): row[1] for row in result.all()}

    users = {}
    if user_ids:
        result = await db.execute(
            select(User.id, User.name, User.email).where(User.id.in_(user_ids))
        )
        users = {str(row[0]): (row[1] or row[2] or "") for row in result.all()}

    return restaurants, users


def _summary(orders: list[Order]) -> dict:
    totals = {
        "orders_total": 0,
        "orders_delivered": 0,
        "orders_cancelled": 0,
        "gross_subtotal": Decimal("0.00"),
        "commissions": Decimal("0.00"),
        "flat_fees": Decimal("0.00"),
        "delivery_fees": Decimal("0.00"),
        "delivery_earnings": Decimal("0.00"),
        "discounts": Decimal("0.00"),
        "tips": Decimal("0.00"),
        "refunds": Decimal("0.00"),
        "cash_collected": Decimal("0.00"),
    }
    for order in orders:
        totals["orders_total"] += 1
        if order.status == "delivered":
            totals["orders_delivered"] += 1
        if order.status == "cancelled":
            totals["orders_cancelled"] += 1
            totals["refunds"] += _money(order.refund_amount)
            continue

        totals["gross_subtotal"] += _money(order.subtotal)
        totals["commissions"] += _money(order.platform_commission)
        totals["flat_fees"] += _money(order.flat_usage_fee)
        totals["delivery_fees"] += _money(order.delivery_fee)
        totals["delivery_earnings"] += _money(order.delivery_earnings)
        totals["discounts"] += _money(order.discount_amount)
        totals["tips"] += _money(order.tip_amount)
        if order.status == "delivered" and order.payment_method == "cash":
            totals["cash_collected"] += _money(order.total)

    totals["platform_revenue"] = totals["commissions"] + totals["flat_fees"]
    totals["net_restaurant"] = totals["gross_subtotal"] - totals["commissions"]
    totals["average_ticket"] = (
        (totals["gross_subtotal"] / totals["orders_delivered"]).quantize(Decimal("0.01"))
        if totals["orders_delivered"]
        else Decimal("0.00")
    )
    return totals


def _serialize(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@router.get("/summary")
async def report_summary(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    restaurant_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant_ids, single = await _scope(db, current_user, restaurant_id)
    start, end, date_from, date_to = await _date_range(db, date_from, date_to)
    tz = await get_timezone(db)
    orders = await _load_orders(db, start, end, restaurant_ids)
    restaurants, _users = await _names(db, orders)
    totals = _summary(orders)

    daily: dict[str, dict] = {}
    by_restaurant: dict[str, dict] = {}
    for order in orders:
        placed = order.placed_at.astimezone(tz) if order.placed_at.tzinfo else order.placed_at
        day_key = placed.date().isoformat()
        day = daily.setdefault(day_key, {
            "date": day_key, "orders": 0, "delivered": 0, "cancelled": 0,
            "subtotal": Decimal("0.00"), "commissions": Decimal("0.00"),
            "flat_fees": Decimal("0.00"), "total": Decimal("0.00"),
        })
        day["orders"] += 1
        if order.status == "delivered":
            day["delivered"] += 1
        if order.status == "cancelled":
            day["cancelled"] += 1
        if order.status != "cancelled":
            day["subtotal"] += _money(order.subtotal)
            day["commissions"] += _money(order.platform_commission)
            day["flat_fees"] += _money(order.flat_usage_fee)
            day["total"] += _money(order.total)

        rid = str(order.restaurant_id)
        bucket = by_restaurant.setdefault(rid, {
            "restaurant_id": rid,
            "restaurant_name": restaurants.get(rid, "—"),
            "orders": 0,
            "subtotal": Decimal("0.00"),
            "commissions": Decimal("0.00"),
            "flat_fees": Decimal("0.00"),
            "total": Decimal("0.00"),
        })
        bucket["orders"] += 1
        if order.status != "cancelled":
            bucket["subtotal"] += _money(order.subtotal)
            bucket["commissions"] += _money(order.platform_commission)
            bucket["flat_fees"] += _money(order.flat_usage_fee)
            bucket["total"] += _money(order.total)

    # Payouts settled in the same window.
    payout_stmt = select(RestaurantPayout).where(
        RestaurantPayout.created_at >= start, RestaurantPayout.created_at < end
    )
    if restaurant_ids:
        payout_stmt = payout_stmt.where(RestaurantPayout.restaurant_id.in_(restaurant_ids))
    restaurant_payouts = list((await db.execute(payout_stmt)).scalars().all())

    delivery_stmt = select(DeliveryPayout).where(
        DeliveryPayout.created_at >= start, DeliveryPayout.created_at < end
    )
    delivery_payouts = list((await db.execute(delivery_stmt)).scalars().all())

    # Courier performance in the same window.
    courier_filter = ""
    courier_params = {"start": start, "end": end}
    if restaurant_ids:
        courier_filter = "AND o.restaurant_id = ANY(:rids)"
        courier_params["rids"] = restaurant_ids
    courier_rows = await db.execute(
        text(f"""
            SELECT dp.id::text AS id, u.name AS name,
                   COUNT(o.id) AS deliveries,
                   COALESCE(SUM(o.delivery_earnings), 0) AS earnings,
                   COALESCE(SUM(o.total), 0) AS sales
            FROM orders o
            JOIN delivery_persons dp ON dp.id = o.delivery_person_id
            JOIN users u ON u.id = dp.user_id
            WHERE o.status = 'delivered'
              AND o.placed_at >= :start AND o.placed_at < :end
              {courier_filter}
            GROUP BY dp.id, u.name
            ORDER BY deliveries DESC, earnings DESC
            LIMIT 25
        """),
        courier_params,
    )
    top_couriers = [
        {
            "id": row.id,
            "name": row.name,
            "deliveries": int(row.deliveries),
            "earnings": f"{_money(row.earnings):.2f}",
            "sales": f"{_money(row.sales):.2f}",
        }
        for row in courier_rows
    ]

    def _payout_totals(rows, amount_attr):
        result = {"pending": Decimal("0.00"), "paid": Decimal("0.00"),
                  "confirmed": Decimal("0.00"), "cancelled": Decimal("0.00")}
        for row in rows:
            status = row.status if row.status in result else "pending"
            result[status] += _money(getattr(row, amount_attr))
        return {k: str(v) for k, v in result.items()}

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "timezone": str(tz),
        "restaurant": {"id": str(single.id), "name": single.name} if single else None,
        "totals": {key: _serialize(value) for key, value in totals.items()},
        "daily": [
            {key: _serialize(value) for key, value in row.items()}
            for row in sorted(daily.values(), key=lambda r: r["date"])
        ],
        "by_restaurant": [
            {key: _serialize(value) for key, value in row.items()}
            for row in sorted(by_restaurant.values(), key=lambda r: r["subtotal"], reverse=True)
        ],
        "top_couriers": top_couriers,
        "restaurant_payouts": _payout_totals(restaurant_payouts, "net_payout"),
        "delivery_payouts": _payout_totals(delivery_payouts, "total_earnings"),
    }


def _csv_response(rows: list[list], header: list[str], filename: str) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    # BOM so Excel opens UTF-8 correctly.
    content = "\ufeff" + buffer.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/orders.csv")
async def export_orders_csv(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    restaurant_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant_ids, _single = await _scope(db, current_user, restaurant_id)
    start, end, date_from, date_to = await _date_range(db, date_from, date_to)
    tz = await get_timezone(db)
    orders = await _load_orders(db, start, end, restaurant_ids)
    restaurants, users = await _names(db, orders)

    rows = []
    for order in orders:
        placed = order.placed_at.astimezone(tz) if order.placed_at.tzinfo else order.placed_at
        rid = str(order.restaurant_id)
        rows.append([
            str(order.id)[:8],
            placed.strftime("%Y-%m-%d %H:%M"),
            restaurants.get(rid, ""),
            users.get(str(order.user_id), ""),
            STATUS_LABELS.get(order.status, order.status),
            PAYMENT_METHOD_LABELS.get(order.payment_method, order.payment_method),
            PAYMENT_STATUS_LABELS.get(order.payment_status, order.payment_status),
            f"{_money(order.subtotal):.2f}",
            f"{_money(order.delivery_fee):.2f}",
            f"{_money(order.flat_usage_fee):.2f}",
            f"{_money(order.platform_commission):.2f}",
            f"{_money(order.discount_amount):.2f}",
            f"{_money(order.tip_amount):.2f}",
            f"{_money(order.total):.2f}",
            f"{_money(order.delivery_earnings):.2f}",
            f"{_money(order.delivery_distance_km):.2f}" if order.delivery_distance_km is not None else "",
            order.cancellation_reason or "",
            f"{_money(order.refund_amount):.2f}",
            REFUND_STATUS_LABELS.get(order.refund_status, order.refund_status or "none"),
            (order.refund_account_holder or "") if current_user.is_superuser else "",
            (order.refund_bank or "") if current_user.is_superuser else "",
            (order.refund_clabe or "") if current_user.is_superuser else "",
        ])

    return _csv_response(
        rows,
        [
            "Folio", "Fecha", "Restaurante", "Cliente", "Estado", "Método de pago",
            "Estado del pago", "Subtotal", "Envío", "Cuota fija", "Comisión",
            "Descuento", "Propina", "Total", "Ganancia repartidor", "Distancia km",
            "Motivo de cancelación", "Reembolso", "Estado del reembolso",
            "Titular reembolso", "Banco reembolso", "CLABE reembolso",
        ],
        f"pedidos_{date_from}_{date_to}.csv",
    )


@router.get("/payouts.csv")
async def export_payouts_csv(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    restaurant_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant_ids, _single = await _scope(db, current_user, restaurant_id)
    start, end, date_from, date_to = await _date_range(db, date_from, date_to)
    tz = await get_timezone(db)

    stmt = select(RestaurantPayout).where(
        RestaurantPayout.created_at >= start, RestaurantPayout.created_at < end
    )
    if restaurant_ids:
        stmt = stmt.where(RestaurantPayout.restaurant_id.in_(restaurant_ids))
    payouts = list((await db.execute(stmt.order_by(RestaurantPayout.created_at.asc()))).scalars().all())

    names = {}
    if payouts:
        result = await db.execute(
            select(Restaurant.id, Restaurant.name).where(
                Restaurant.id.in_({p.restaurant_id for p in payouts})
            )
        )
        names = {str(row[0]): row[1] for row in result.all()}

    rows = []
    for payout in payouts:
        created = payout.created_at.astimezone(tz) if payout.created_at.tzinfo else payout.created_at
        rows.append([
            str(payout.id)[:8],
            created.strftime("%Y-%m-%d %H:%M"),
            names.get(str(payout.restaurant_id), ""),
            payout.period_start.isoformat(),
            payout.period_end.isoformat(),
            payout.orders_count,
            f"{_money(payout.total_subtotal):.2f}",
            f"{_money(payout.total_commission):.2f}",
            f"{_money(payout.total_flat_fees):.2f}",
            f"{_money(payout.net_payout):.2f}",
            payout.status,
            payout.paid_at.isoformat() if payout.paid_at else "",
        ])

    return _csv_response(
        rows,
        [
            "Folio", "Solicitada", "Restaurante", "Periodo inicio", "Periodo fin",
            "Pedidos", "Subtotal", "Comisión", "Cuotas", "Liquidación neta",
            "Estado", "Pagada",
        ],
        f"liquidaciones_{date_from}_{date_to}.csv",
    )
