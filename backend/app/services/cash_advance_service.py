"""Cash advances for couriers to pay restaurants at pickup."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_advance import CashAdvance
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order

ACTIVE_STATUSES = ("pending", "approved")


async def active_advance_for_order(db: AsyncSession, order_id):
    result = await db.execute(
        select(CashAdvance).where(
            CashAdvance.order_id == order_id,
            CashAdvance.status.in_(ACTIVE_STATUSES),
        )
    )
    return result.scalar_one_or_none()


def restaurant_net(order: Order) -> Decimal:
    return (
        (order.subtotal or Decimal("0"))
        - (order.platform_commission or Decimal("0"))
    ).quantize(Decimal("0.01"))


async def create_advance_request(
    db: AsyncSession,
    dp: DeliveryPerson,
    order: Order,
    notes: str | None = None,
) -> CashAdvance:
    if order.delivery_person_id != dp.id:
        raise ValueError("El pedido no está asignado a este repartidor")
    if order.status in ("delivered", "cancelled"):
        raise ValueError("El pedido ya no permite solicitar avance")
    if await active_advance_for_order(db, order.id):
        raise ValueError("Ya existe un avance activo para este pedido")

    amount = restaurant_net(order)
    if amount <= 0:
        raise ValueError("El pedido no tiene monto para pagar al restaurante")

    advance = CashAdvance(
        delivery_person_id=dp.id,
        order_id=order.id,
        amount=amount,
        status="pending",
        pays_restaurant=True,
        notes=notes,
    )
    db.add(advance)
    await db.commit()
    await db.refresh(advance)
    return advance


async def approve_advance(
    db: AsyncSession,
    advance: CashAdvance,
    approved_by,
    pays_restaurant: bool = True,
) -> CashAdvance:
    if advance.status != "pending":
        raise ValueError("El avance ya fue procesado")
    advance.status = "approved"
    advance.approved_by = approved_by
    advance.taken_at = datetime.now(timezone.utc)
    advance.pays_restaurant = pays_restaurant
    if pays_restaurant and advance.order_id:
        order = await db.get(Order, advance.order_id)
        if order:
            order.restaurant_paid_with_advance = True
    await db.commit()
    await db.refresh(advance)
    return advance


async def reject_advance(db: AsyncSession, advance: CashAdvance) -> CashAdvance:
    if advance.status != "pending":
        raise ValueError("El avance ya fue procesado")
    advance.status = "rejected"
    await db.commit()
    await db.refresh(advance)
    return advance


async def settle_advance(
    db: AsyncSession,
    advance: CashAdvance,
    method: str = "cash",
) -> CashAdvance:
    if advance.status not in ("pending", "approved"):
        raise ValueError("El avance ya fue liquidado")
    advance.status = "settled"
    advance.settled_at = datetime.now(timezone.utc)
    advance.settlement_method = method
    await db.commit()
    await db.refresh(advance)
    return advance


async def advance_debt(db: AsyncSession, dp: DeliveryPerson) -> Decimal:
    """Loan advances (not restaurant payments) still owed by the courier."""
    result = await db.execute(
        select(func.coalesce(func.sum(CashAdvance.amount), 0)).where(
            CashAdvance.delivery_person_id == dp.id,
            CashAdvance.status == "approved",
            CashAdvance.pays_restaurant.is_(False),
        )
    )
    return Decimal(str(result.scalar_one() or 0))


async def settle_advances_for_payout(db: AsyncSession, dp: DeliveryPerson) -> Decimal:
    """Mark loan advances as deducted by a payout and return the total."""
    result = await db.execute(
        select(CashAdvance).where(
            CashAdvance.delivery_person_id == dp.id,
            CashAdvance.status == "approved",
            CashAdvance.pays_restaurant.is_(False),
        )
    )
    advances = list(result.scalars().all())
    total = sum((adv.amount or Decimal("0")) for adv in advances)
    now = datetime.now(timezone.utc)
    for advance in advances:
        advance.status = "settled"
        advance.settled_at = now
        advance.settlement_method = "payout"
    return total


async def settle_restaurant_advances_for_order(db: AsyncSession, order: Order) -> None:
    """Close restaurant-payment advances once the order is delivered."""
    result = await db.execute(
        select(CashAdvance).where(
            CashAdvance.order_id == order.id,
            CashAdvance.status == "approved",
            CashAdvance.pays_restaurant.is_(True),
        )
    )
    now = datetime.now(timezone.utc)
    for advance in result.scalars().all():
        advance.status = "settled"
        advance.settled_at = now
        advance.settlement_method = "restaurant_payment"
