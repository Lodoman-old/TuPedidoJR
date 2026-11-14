"""Admin payout center: individual restaurant and courier settlements."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.cash_advance import CashAdvance
from app.models.delivery_payout import DeliveryPayout
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.reservation import Reservation
from app.models.restaurant import Restaurant
from app.models.restaurant_payout import RestaurantPayout
from app.models.user import User
from app.schemas.cash_advance import AdminCashAdvanceOut, CashAdvanceApprove
from app.services.cash_advance_service import (
    approve_advance,
    reject_advance,
    settle_advance,
)
from app.services.order_service import get_setting_value
from app.services.push_service import schedule_new_reservation
from app.services.payout_service import (
    courier_balance,
    create_courier_payout,
    create_restaurant_payout,
    next_payout_date,
    restaurant_balance,
)
from app.services.audit_service import log_action

router = APIRouter()


def _money(value) -> str:
    return f"{float(value or 0):.2f}"


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


def _first_pending_date(orders):
    dates = [o.placed_at.date() for o in orders if o.placed_at]
    return min(dates) if dates else None


def _due_state(pending, next_date: date | None) -> str:
    if pending <= 0:
        return "paid_up"
    if next_date and next_date <= date.today():
        return "due"
    return "scheduled"


@router.get("/refunds/pending")
async def pending_refunds(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(Order, User, Restaurant)
        .outerjoin(User, User.id == Order.user_id)
        .outerjoin(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(Order.refund_status == "pending")
        .order_by(Order.cancelled_at.desc().nullslast())
    )
    rows = []
    for order, customer, restaurant in result.all():
        rows.append({
            "id": str(order.id),
            "restaurant_name": restaurant.name if restaurant else "",
            "customer_name": customer.name if customer else "",
            "customer_email": customer.email if customer else "",
            "total": str(order.refund_amount or order.total or 0),
            "account_holder": order.refund_account_holder,
            "bank": order.refund_bank,
            "clabe": order.refund_clabe,
            "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
        })
    return rows


@router.post("/refunds/{order_id}/mark-refunded")
async def mark_refunded(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.refund_status != "pending":
        raise HTTPException(status_code=400, detail="El pedido no tiene un reembolso pendiente")
    order.refund_status = "refunded"
    order.payment_status = "refunded"
    await log_action(
        db, current_user.id, "refund.marked", "order", order.id,
        {"amount": str(order.refund_amount or 0)},
    )
    await db.commit()
    return {"ok": True, "refund_status": order.refund_status}


def _reservation_deposit_row(reservation: Reservation, restaurant, user) -> dict:
    deposit = Decimal(reservation.deposit_amount or 0)
    commission = Decimal(reservation.commission_amount or 0)
    service_fee = Decimal(reservation.service_fee or 0)
    net_deposit = max(deposit - commission, Decimal("0")) if deposit > 0 else Decimal("0")
    restaurant_owes = commission + service_fee if reservation.service_fee_cash else Decimal("0")
    return {
        "id": str(reservation.id),
        "restaurant_id": str(reservation.restaurant_id),
        "restaurant_name": restaurant.name if restaurant else "",
        "customer_name": user.name if user else "",
        "customer_email": user.email if user else "",
        "reservation_at": reservation.reservation_at.isoformat() if reservation.reservation_at else None,
        "party_size": reservation.party_size,
        "status": reservation.status,
        "preorder_subtotal": _money(reservation.preorder_subtotal),
        "service_fee": _money(service_fee),
        "service_fee_cash": bool(reservation.service_fee_cash),
        "service_fee_status": reservation.service_fee_status,
        "deposit_amount": _money(deposit),
        "deposit_status": reservation.deposit_status,
        "deposit_method": reservation.deposit_method,
        "deposit_proof_url": reservation.deposit_proof_url,
        "commission_amount": _money(commission),
        "commission_status": reservation.commission_status,
        "remaining_to_charge": _money(reservation.remaining_to_charge),
        "deposit_settlement_status": reservation.deposit_settlement_status,
        "net_deposit_to_restaurant": _money(net_deposit),
        "restaurant_owes": _money(restaurant_owes),
    }


@router.get("/reservation-deposits")
async def list_reservation_deposits(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(Reservation, Restaurant, User)
        .outerjoin(Restaurant, Restaurant.id == Reservation.restaurant_id)
        .outerjoin(User, User.id == Reservation.user_id)
        .where(
            (Reservation.deposit_amount > 0)
            | (Reservation.service_fee_cash.is_(True))
            | (Reservation.commission_status == "pending")
        )
        .order_by(Reservation.created_at.desc())
        .limit(200)
    )
    return [_reservation_deposit_row(r, resto, user) for r, resto, user in result.all()]


@router.post("/reservation-deposits/{reservation_id}/confirm")
async def confirm_reservation_deposit(
    reservation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    reservation = await db.get(Reservation, _uuid(reservation_id))
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    if reservation.deposit_status != "pending":
        raise HTTPException(status_code=400, detail="El depósito no está pendiente")
    reservation.deposit_status = "paid"
    reservation.deposit_settlement_status = "pending"
    if reservation.status == "pending_deposit":
        reservation.status = "requested"
    await log_action(
        db, current_user.id, "reservation.deposit.confirm", "reservation", reservation.id,
        {"amount": _money(reservation.deposit_amount)},
    )
    await db.commit()
    schedule_new_reservation(str(reservation.id), deposit_pending=False)
    return _reservation_deposit_row(reservation, None, None)


@router.post("/reservation-deposits/{reservation_id}/transfer")
async def transfer_reservation_deposit(
    reservation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    reservation = await db.get(Reservation, _uuid(reservation_id))
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    if reservation.deposit_status not in ("paid", "retained") or reservation.deposit_amount <= 0:
        raise HTTPException(status_code=400, detail="No hay depósito por transferir")
    reservation.deposit_settlement_status = "transferred"
    reservation.commission_status = "settled"
    await log_action(
        db, current_user.id, "reservation.deposit.transfer", "reservation", reservation.id,
        {"net": _money(max(reservation.deposit_amount - reservation.commission_amount, 0))},
    )
    await db.commit()
    return _reservation_deposit_row(reservation, None, None)


@router.post("/reservation-deposits/{reservation_id}/refund")
async def refund_reservation_deposit(
    reservation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    reservation = await db.get(Reservation, _uuid(reservation_id))
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    if reservation.deposit_amount <= 0:
        raise HTTPException(status_code=400, detail="No hay depósito por reembolsar")
    reservation.deposit_status = "refunded"
    reservation.deposit_settlement_status = "refunded"
    reservation.commission_status = "settled"
    if reservation.status not in ("completed", "no_show", "cancelled", "rejected"):
        reservation.status = "cancelled"
    await log_action(
        db, current_user.id, "reservation.deposit.refund", "reservation", reservation.id,
        {"amount": _money(reservation.deposit_amount)},
    )
    await db.commit()
    return _reservation_deposit_row(reservation, None, None)


@router.post("/reservation-fees/{reservation_id}/settle")
async def settle_reservation_fee(
    reservation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    reservation = await db.get(Reservation, _uuid(reservation_id))
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    reservation.commission_status = "settled"
    if reservation.service_fee_cash:
        reservation.service_fee_status = "settled"
    await log_action(
        db, current_user.id, "reservation.fee.settle", "reservation", reservation.id,
        {"amount": _money(reservation.commission_amount)},
    )
    await db.commit()
    return _reservation_deposit_row(reservation, None, None)


@router.get("/payouts")
async def admin_payouts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    global_commission = await get_setting_value(db, "APP_COMMISSION_PERCENTAGE", "15.0")

    restaurants_result = await db.execute(select(Restaurant).order_by(Restaurant.name))
    restaurants = []
    for restaurant in restaurants_result.scalars().all():
        balance = await restaurant_balance(db, restaurant.id)
        next_date = next_payout_date(
            balance["last_payout"],
            restaurant.payout_frequency_days,
            _first_pending_date(balance["orders"]),
        )
        commission = (
            restaurant.commission_percentage
            if restaurant.commission_percentage is not None
            else global_commission
        )
        cutoff = date.today() - timedelta(days=30)
        monthly_sales = sum(
            (o.subtotal or 0)
            for o in balance["orders"]
            if o.placed_at and o.placed_at.date() >= cutoff
        )
        restaurants.append({
            "id": str(restaurant.id),
            "name": restaurant.name,
            "commission_percentage": _money(commission),
            "uses_global_commission": restaurant.commission_percentage is None,
            "payout_frequency_days": restaurant.payout_frequency_days,
            "pending_amount": _money(balance["pending"]),
            "earned_total": _money(balance["earned"]),
            "restaurant_debt": _money(balance.get("cash_debt", 0)),
            "monthly_sales": _money(monthly_sales),
            "last_payout_date": balance["last_payout"].isoformat() if balance["last_payout"] else None,
            "next_payout_date": next_date.isoformat(),
            "status": _due_state(balance["pending"], next_date),
            "pending_orders": len(balance["orders"]),
        })

    couriers_result = await db.execute(
        select(DeliveryPerson, User)
        .join(User, User.id == DeliveryPerson.user_id)
        .order_by(User.name)
    )
    couriers = []
    for dp, user in couriers_result.all():
        balance = await courier_balance(db, dp)
        next_date = next_payout_date(
            balance["last_payout"],
            dp.payout_frequency_days,
            _first_pending_date(balance["orders"]),
        )
        couriers.append({
            "id": str(dp.id),
            "user_id": str(user.id),
            "name": user.name or user.email,
            "email": user.email,
            "payout_method": dp.payout_method,
            "bank_name": dp.bank_name,
            "bank_account_holder": dp.bank_account_holder,
            "bank_clabe": dp.bank_clabe,
            "payout_frequency_days": dp.payout_frequency_days,
            "delivery_bonus_per_order": _money(dp.delivery_bonus_per_order),
            "pending_amount": _money(balance["pending"]),
            "earned_total": _money(balance["earned"]),
            "pending_debt": _money(balance["debt"]),
            "pending_advances": _money(balance["advances"]),
            "last_payout_date": balance["last_payout"].isoformat() if balance["last_payout"] else None,
            "next_payout_date": next_date.isoformat(),
            "status": _due_state(balance["pending"], next_date),
            "pending_deliveries": len(balance["orders"]),
        })

    transfers_result = await db.execute(
        select(Order, Restaurant.name)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(
            Order.payment_method == "transfer",
            Order.payment_status.in_(["pending", "in_process"]),
            Order.status != "cancelled",
        )
        .order_by(Order.placed_at.desc())
        .limit(100)
    )
    pending_transfers = [
        {
            "id": str(order.id),
            "restaurant_name": name,
            "amount": _money(order.total),
            "status": order.status,
            "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        }
        for order, name in transfers_result.all()
    ]

    return {
        "restaurants": restaurants,
        "couriers": couriers,
        "pending_transfers": pending_transfers,
        "today": date.today().isoformat(),
    }


@router.get("/payouts/reconciliation")
async def payout_reconciliation(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    today = date.today()
    start_date = start_date or today.replace(day=1)
    end_date = end_date or today
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="La fecha final no puede ser menor a la inicial")
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    from sqlalchemy import func

    delivered_at = func.coalesce(Order.delivered_at, Order.placed_at)
    result = await db.execute(
        select(Order, Restaurant.name)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(
            Order.status == "delivered",
            delivered_at >= start_dt,
            delivered_at < end_dt,
        )
        .order_by(Order.created_at)
    )
    orders = result.all()

    restaurant_rows: dict[str, dict] = {}
    courier_rows: dict[str, dict] = {}
    totals = {
        "orders": 0, "subtotal": Decimal("0"), "commission": Decimal("0"),
        "flat_fee": Decimal("0"), "tips": Decimal("0"), "delivery_fees": Decimal("0"),
        "total": Decimal("0"), "restaurant_owes": Decimal("0"),
        "courier_earnings": Decimal("0"), "cash_orders": 0, "transfer_orders": 0,
        "loyalty_discount": Decimal("0"),
    }

    for order, restaurant_name in orders:
        subtotal = Decimal(order.subtotal or 0)
        commission = Decimal(order.platform_commission or 0)
        flat_fee = Decimal(order.flat_usage_fee or 0)
        tips = Decimal(order.tip_amount or 0)
        delivery_fee = Decimal(order.delivery_fee or 0)
        total = Decimal(order.total or 0)
        owes = Decimal(order.restaurant_owes_platform or 0)
        earnings = Decimal(order.delivery_earnings or 0)

        key = str(order.restaurant_id)
        row = restaurant_rows.setdefault(key, {
            "restaurant_id": key, "name": restaurant_name, "orders": 0,
            "subtotal": Decimal("0"), "commission": Decimal("0"),
            "flat_fee": Decimal("0"), "tips": Decimal("0"),
            "delivery_fees": Decimal("0"), "total": Decimal("0"),
            "restaurant_owes": Decimal("0"), "courier_earnings": Decimal("0"),
            "loyalty_discount": Decimal("0"),
        })
        row["orders"] += 1
        row["subtotal"] += subtotal
        row["commission"] += commission
        row["flat_fee"] += flat_fee
        row["tips"] += tips
        row["delivery_fees"] += delivery_fee
        row["total"] += total
        row["restaurant_owes"] += owes
        row["courier_earnings"] += earnings
        row["loyalty_discount"] += Decimal(order.loyalty_discount or 0)

        totals["orders"] += 1
        totals["subtotal"] += subtotal
        totals["commission"] += commission
        totals["flat_fee"] += flat_fee
        totals["tips"] += tips
        totals["delivery_fees"] += delivery_fee
        totals["total"] += total
        totals["restaurant_owes"] += owes
        totals["courier_earnings"] += earnings
        totals["loyalty_discount"] += Decimal(order.loyalty_discount or 0)
        if order.payment_method == "cash":
            totals["cash_orders"] += 1
        elif order.payment_method == "transfer":
            totals["transfer_orders"] += 1

        if order.delivery_person_id:
            courier_key = str(order.delivery_person_id)
            courier_row = courier_rows.setdefault(courier_key, {
                "delivery_person_id": courier_key, "name": "", "orders": 0,
                "earnings": Decimal("0"), "tips": Decimal("0"), "cash_orders": 0,
            })
            courier_row["orders"] += 1
            courier_row["earnings"] += earnings
            courier_row["tips"] += tips
            if order.payment_method == "cash":
                courier_row["cash_orders"] += 1

    if courier_rows:
        courier_result = await db.execute(
            select(DeliveryPerson.id, User.name)
            .join(User, User.id == DeliveryPerson.user_id)
            .where(DeliveryPerson.id.in_([uuid.UUID(k) for k in courier_rows]))
        )
        for dp_id, name in courier_result.all():
            if str(dp_id) in courier_rows:
                courier_rows[str(dp_id)]["name"] = name

    def _serialize(row: dict) -> dict:
        return {
            key: (_money(value) if isinstance(value, Decimal) else value)
            for key, value in row.items()
        }

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "totals": _serialize(totals),
        "restaurants": sorted(
            (_serialize(row) for row in restaurant_rows.values()),
            key=lambda item: float(item["total"]), reverse=True,
        ),
        "couriers": sorted(
            (_serialize(row) for row in courier_rows.values()),
            key=lambda item: float(item["earnings"]), reverse=True,
        ),
    }


@router.post("/payouts/restaurants/{restaurant_id}")
async def generate_restaurant_payout(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    try:
        payout = await create_restaurant_payout(db, _uuid(restaurant_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(
        db, current_user.id, "payout.restaurant.generate", "restaurant_payout",
        payout.id, {"amount": _money(payout.net_payout)},
    )
    await db.commit()
    return {
        "id": str(payout.id),
        "kind": "restaurant",
        "amount": _money(payout.net_payout),
        "status": payout.status,
    }


@router.post("/payouts/couriers/{dp_id}")
async def generate_courier_payout(
    dp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    dp = await db.get(DeliveryPerson, _uuid(dp_id))
    if not dp:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    try:
        payout = await create_courier_payout(db, dp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(
        db, current_user.id, "payout.courier.generate", "delivery_payout",
        payout.id, {"amount": _money(payout.total_earnings)},
    )
    await db.commit()
    return {
        "id": str(payout.id),
        "kind": "courier",
        "amount": _money(payout.total_earnings),
        "status": payout.status,
    }


@router.get("/advances", response_model=list[AdminCashAdvanceOut])
async def admin_cash_advances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(CashAdvance, User.name, Restaurant.name)
        .join(DeliveryPerson, DeliveryPerson.id == CashAdvance.delivery_person_id)
        .join(User, User.id == DeliveryPerson.user_id)
        .outerjoin(Order, Order.id == CashAdvance.order_id)
        .outerjoin(Restaurant, Restaurant.id == Order.restaurant_id)
        .order_by(CashAdvance.taken_at.desc())
        .limit(200)
    )
    rows = []
    for advance, courier_name, restaurant_name in result.all():
        item = AdminCashAdvanceOut.model_validate(advance)
        item.courier_name = courier_name
        item.restaurant_name = restaurant_name
        rows.append(item)
    return rows


@router.post("/advances/{advance_id}/approve", response_model=AdminCashAdvanceOut)
async def approve_cash_advance(
    advance_id: str,
    body: CashAdvanceApprove,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    advance = await db.get(CashAdvance, _uuid(advance_id))
    if not advance:
        raise HTTPException(status_code=404, detail="Avance no encontrado")
    try:
        result = await approve_advance(
            db, advance, current_user.id, body.pays_restaurant,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(
        db, current_user.id, "advance.approve", "cash_advance", advance.id,
        {"amount": _money(advance.amount), "pays_restaurant": body.pays_restaurant},
    )
    await db.commit()
    return result


@router.post("/advances/{advance_id}/reject", response_model=AdminCashAdvanceOut)
async def reject_cash_advance(
    advance_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    advance = await db.get(CashAdvance, _uuid(advance_id))
    if not advance:
        raise HTTPException(status_code=404, detail="Avance no encontrado")
    try:
        result = await reject_advance(db, advance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(db, current_user.id, "advance.reject", "cash_advance", advance.id, {"amount": _money(advance.amount)})
    await db.commit()
    return result


@router.post("/advances/{advance_id}/settle", response_model=AdminCashAdvanceOut)
async def settle_cash_advance(
    advance_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    advance = await db.get(CashAdvance, _uuid(advance_id))
    if not advance:
        raise HTTPException(status_code=404, detail="Avance no encontrado")
    try:
        result = await settle_advance(db, advance, method="cash")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(db, current_user.id, "advance.settle", "cash_advance", advance.id, {"amount": _money(advance.amount)})
    await db.commit()
    return result


@router.post("/payouts/transfers/{order_id}/confirm")
async def confirm_transfer_received(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    order = await db.get(Order, _uuid(order_id))
    if not order or order.payment_method != "transfer":
        raise HTTPException(status_code=404, detail="Transferencia no encontrada")
    order.payment_status = "approved"
    await log_action(
        db, current_user.id, "transfer.confirm", "order", order.id,
        {"total": _money(order.total)},
    )
    await db.commit()
    return {"id": str(order.id), "payment_status": order.payment_status}


@router.post("/payouts/{kind}/{payout_id}/mark-paid")
async def mark_payout_paid(
    kind: str,
    payout_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    if kind not in ("restaurant", "courier"):
        raise HTTPException(status_code=400, detail="Tipo de liquidación inválido")
    model = RestaurantPayout if kind == "restaurant" else DeliveryPayout
    payout = await db.get(model, _uuid(payout_id))
    if not payout:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada")
    now = datetime.now(timezone.utc)
    payout.status = "paid"
    payout.paid_at = now
    payout.confirmed_at = now
    await log_action(
        db, current_user.id, f"payout.{kind}.paid", f"{kind}_payout", payout.id,
        {"amount": _money(getattr(payout, "net_payout", None) or getattr(payout, "total_earnings", None))},
    )
    await db.commit()
    return {"id": str(payout.id), "status": payout.status}


@router.get("/payouts/history")
async def payout_history(
    limit: int = 60,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    restaurant_result = await db.execute(
        select(RestaurantPayout, Restaurant.name)
        .join(Restaurant, Restaurant.id == RestaurantPayout.restaurant_id)
        .order_by(RestaurantPayout.created_at.desc())
        .limit(limit)
    )
    courier_result = await db.execute(
        select(DeliveryPayout, User.name)
        .join(DeliveryPerson, DeliveryPerson.id == DeliveryPayout.delivery_person_id)
        .join(User, User.id == DeliveryPerson.user_id)
        .order_by(DeliveryPayout.created_at.desc())
        .limit(limit)
    )

    history = []
    for payout, name in restaurant_result.all():
        history.append({
            "id": str(payout.id),
            "kind": "restaurant",
            "name": name,
            "amount": _money(payout.net_payout),
            "status": payout.status,
            "period_start": payout.period_start.isoformat(),
            "period_end": payout.period_end.isoformat(),
            "created_at": payout.created_at.isoformat(),
            "paid_at": payout.paid_at.isoformat() if payout.paid_at else None,
        })
    for payout, name in courier_result.all():
        history.append({
            "id": str(payout.id),
            "kind": "courier",
            "name": name,
            "amount": _money(payout.total_earnings),
            "status": payout.status,
            "period_start": payout.period_start.isoformat(),
            "period_end": payout.period_end.isoformat(),
            "created_at": payout.created_at.isoformat(),
            "paid_at": payout.paid_at.isoformat() if payout.paid_at else None,
        })
    history.sort(key=lambda row: row["created_at"], reverse=True)
    return history[:limit]

