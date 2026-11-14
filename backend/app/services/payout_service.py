"""Payout balances shared by courier/restaurant requests and the admin panel."""
import random
import string
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery_payout import DeliveryPayout
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant_payout import RestaurantPayout
from app.models.shipment import Shipment
from app.services.settlement_service import is_order_settleable


async def restaurant_balance(db: AsyncSession, restaurant_id) -> dict:
    orders_result = await db.execute(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.status == "delivered",
        )
    )
    orders = [
        order for order in orders_result.scalars().all()
        if is_order_settleable(order) and not order.restaurant_paid_with_advance
    ]

    def _net(order: Order) -> Decimal:
        base = (order.subtotal or Decimal("0")) - (order.platform_commission or Decimal("0"))
        if order.delivery_mode == "own":
            base += order.delivery_fee or Decimal("0")
            base += order.tip_amount or Decimal("0")
        return base

    payable_orders = [
        order for order in orders
        if not (order.delivery_mode in ("own", "pickup") and order.payment_method == "cash")
    ]
    earnable = sum((_net(o) for o in payable_orders), Decimal("0"))
    loyalty_credit = sum(
        (
            max(
                (o.loyalty_discount or Decimal("0"))
                - (o.platform_commission or Decimal("0"))
                - (o.flat_usage_fee or Decimal("0")),
                Decimal("0"),
            )
            for o in orders
            if o.delivery_mode in ("own", "pickup")
            and o.payment_method == "cash"
            and not o.restaurant_charge_settled
        ),
        Decimal("0"),
    )
    earned = earnable + loyalty_credit
    cash_debt = sum(
        (o.restaurant_owes_platform or Decimal("0"))
        for o in orders
        if o.delivery_mode in ("own", "pickup")
        and o.payment_method == "cash"
        and not o.restaurant_charge_settled
    )

    payouts_result = await db.execute(
        select(RestaurantPayout).where(
            RestaurantPayout.restaurant_id == restaurant_id,
            RestaurantPayout.status != "cancelled",
        )
    )
    payouts = list(payouts_result.scalars().all())
    requested = sum((p.net_payout or Decimal("0")) for p in payouts)

    shipments_result = await db.execute(
        select(Shipment).where(
            Shipment.store_id == restaurant_id,
            Shipment.status.in_(("delivered", "failed")),
        )
    )
    shipments = list(shipments_result.scalars().all())
    shipment_credit = sum(
        (s.store_credit or Decimal("0"))
        for s in shipments
        if s.status == "delivered" and not s.store_credit_settled
    )
    shipment_charge = sum(
        (s.store_charge or Decimal("0"))
        for s in shipments
        if not s.store_charge_settled
    )
    earned += shipment_credit
    cash_debt += shipment_charge

    pending = max(earned - requested - cash_debt, Decimal("0"))

    return {
        "orders": payable_orders,
        "all_orders": orders,
        "shipments": shipments,
        "earned": earned,
        "requested": requested,
        "cash_debt": cash_debt,
        "shipment_credit": shipment_credit,
        "shipment_charge": shipment_charge,
        "loyalty_credit": loyalty_credit,
        "pending": pending,
        "last_payout": max(
            (p.period_end for p in payouts if p.period_end),
            default=None,
        ),
    }


async def courier_balance(db: AsyncSession, dp: DeliveryPerson) -> dict:
    orders_result = await db.execute(
        select(Order).where(
            Order.delivery_person_id == dp.id,
            Order.status == "delivered",
        )
    )
    orders = [
        order for order in orders_result.scalars().all()
        if is_order_settleable(order)
    ]
    earned = sum((o.delivery_earnings or Decimal("0")) for o in orders)

    shipments_result = await db.execute(
        select(Shipment).where(
            Shipment.delivery_person_id == dp.id,
            Shipment.status.in_(("delivered", "failed")),
            Shipment.courier_settled.is_(False),
        )
    )
    shipments = list(shipments_result.scalars().all())
    shipment_earnings = sum(
        (s.courier_earnings or Decimal("0")) for s in shipments
    )
    earned += shipment_earnings

    payouts_result = await db.execute(
        select(DeliveryPayout).where(
            DeliveryPayout.delivery_person_id == dp.id,
            DeliveryPayout.status != "cancelled",
        )
    )
    payouts = list(payouts_result.scalars().all())
    requested = sum((p.total_earnings or Decimal("0")) for p in payouts)
    debt = dp.pending_platform_debt or Decimal("0")
    from app.services.cash_advance_service import advance_debt
    advances = await advance_debt(db, dp)
    pending = max(earned - requested - debt - advances, Decimal("0"))

    return {
        "orders": orders,
        "shipments": shipments,
        "shipment_earnings": shipment_earnings,
        "earned": earned,
        "requested": requested,
        "debt": debt,
        "advances": advances,
        "pending": pending,
        "last_payout": max(
            (p.period_end for p in payouts if p.period_end),
            default=None,
        ),
    }


def next_payout_date(last_payout, frequency_days: int, first_pending=None) -> date:
    if frequency_days is None:
        frequency_days = 1
    if int(frequency_days) <= 0:
        return date.today()
    base = last_payout or first_pending or date.today()
    return base + timedelta(days=max(int(frequency_days), 1))


def _period(orders: list[Order], last_payout) -> tuple[date, date]:
    today = date.today()
    first = min(
        (o.placed_at.date() for o in orders if o.placed_at),
        default=today,
    )
    start = (last_payout + timedelta(days=1)) if last_payout else first
    return start, today


async def create_restaurant_payout(db: AsyncSession, restaurant_id) -> RestaurantPayout:
    balance = await restaurant_balance(db, restaurant_id)
    if balance["pending"] <= 0:
        raise ValueError("No hay saldo disponible para liquidar")

    orders = balance["orders"]
    period_start, period_end = _period(orders, balance["last_payout"])
    for order in balance["all_orders"]:
        if (
            order.delivery_mode in ("own", "pickup")
            and order.payment_method == "cash"
            and not order.restaurant_charge_settled
        ):
            order.restaurant_charge_settled = True
    settled_shipments = 0
    for shipment in balance.get("shipments", []):
        if shipment.status == "delivered" and not shipment.store_credit_settled:
            shipment.store_credit_settled = True
            settled_shipments += 1
        if not shipment.store_charge_settled:
            shipment.store_charge_settled = True
    payout = RestaurantPayout(
        restaurant_id=restaurant_id,
        period_start=period_start,
        period_end=period_end,
        orders_count=len(orders),
        total_subtotal=sum((o.subtotal or Decimal("0")) for o in orders),
        total_commission=sum((o.platform_commission or Decimal("0")) for o in orders),
        total_flat_fees=sum((o.flat_usage_fee or Decimal("0")) for o in orders),
        net_payout=balance["pending"],
        status="pending",
        notes=(
            f"Incluye {settled_shipments} envío(s) de negocio liquidado(s)."
            if settled_shipments else None
        ),
    )
    db.add(payout)
    await db.commit()
    await db.refresh(payout)
    return payout


async def create_courier_payout(db: AsyncSession, dp: DeliveryPerson) -> DeliveryPayout:
    balance = await courier_balance(db, dp)
    if balance["pending"] <= 0:
        raise ValueError("No hay saldo disponible para liquidar")

    orders = balance["orders"]
    period_start, period_end = _period(orders, balance["last_payout"])
    from app.services.cash_advance_service import settle_advances_for_payout

    await settle_advances_for_payout(db, dp)
    payout = DeliveryPayout(
        id=uuid.uuid4(),
        delivery_person_id=dp.id,
        period_start=period_start,
        period_end=period_end,
        orders_count=len(orders),
        total_earnings=balance["pending"],
        payout_method=dp.payout_method or "cash",
        confirmation_code="".join(random.choices(string.digits, k=6)),
        status="pending",
    )
    for shipment in balance.get("shipments", []):
        shipment.courier_settled = True
    db.add(payout)
    # The payout amount already deducted the cash debt, so clear it to avoid
    # discounting the same debt again from future earnings.
    dp.pending_platform_debt = Decimal("0")
    await db.commit()
    await db.refresh(payout)
    return payout
