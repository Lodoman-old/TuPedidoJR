"""Recargas: flujo manual mientras se integra un proveedor."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.recarga_order import RecargaOrder
from app.models.user import User

RECARGA_FEE = Decimal("2.00")
CHECKOUT_RECHARGE_FEE = Decimal("2.00")
MIN_RECHARGE = Decimal("10.00")
MAX_RECHARGE = Decimal("500.00")
CASH_METHODS = {"cash"}


def _now():
    return datetime.now(timezone.utc)


def normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) != 10:
        raise ValueError("Escribe un número de teléfono de 10 dígitos")
    return digits


def _apply_cash_accounting(dp: DeliveryPerson, recarga: RecargaOrder) -> None:
    if recarga.origin == "checkout":
        # En las recargas agregadas al pedido, el efectivo se liquida junto
        # con el total del pedido; no se abona comisión al repartidor.
        return
    if recarga.payment_method not in CASH_METHODS:
        return
    if recarga.payment_status != "paid":
        return
    if not recarga.debt_applied:
        dp.pending_platform_debt = (dp.pending_platform_debt or Decimal("0")) + recarga.amount
        recarga.debt_applied = True
    if not recarga.credit_applied and (recarga.fee or Decimal("0")) > 0:
        dp.pending_platform_credit = (dp.pending_platform_credit or Decimal("0")) + recarga.fee
        recarga.credit_applied = True


def _reverse_cash_accounting(dp: DeliveryPerson, recarga: RecargaOrder) -> None:
    if recarga.debt_applied:
        dp.pending_platform_debt = (dp.pending_platform_debt or Decimal("0")) - recarga.amount
        recarga.debt_applied = False
    if recarga.credit_applied:
        dp.pending_platform_credit = (dp.pending_platform_credit or Decimal("0")) - (recarga.fee or Decimal("0"))
        recarga.credit_applied = False


async def create_cash_recarga(
    db: AsyncSession,
    dp: DeliveryPerson,
    *,
    company: str,
    phone: str,
    amount: Decimal,
    order: Order | None = None,
    customer_name: str | None = None,
) -> RecargaOrder:
    phone = normalize_phone(phone)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValueError("Escribe un monto válido")
    if order is not None and order.delivery_person_id != dp.id:
        raise ValueError("El pedido no está asignado a este repartidor")

    recarga = RecargaOrder(
        user_id=order.user_id if order else None,
        customer_name=(customer_name or "").strip() or None,
        delivery_person_id=dp.id,
        order_id=order.id if order else None,
        origin="courier",
        company=company.strip(),
        phone=phone,
        amount=amount,
        fee=RECARGA_FEE,
        total=amount + RECARGA_FEE,
        payment_method="cash",
        payment_status="paid",
        status="pending",
        paid_at=_now(),
    )
    _apply_cash_accounting(dp, recarga)
    db.add(recarga)
    await db.commit()
    await db.refresh(recarga)
    return recarga


async def create_transfer_recarga(
    db: AsyncSession,
    user: User,
    *,
    company: str,
    phone: str,
    amount: Decimal,
    customer_name: str | None = None,
) -> RecargaOrder:
    phone = normalize_phone(phone)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValueError("Escribe un monto válido")
    recarga = RecargaOrder(
        user_id=user.id,
        customer_name=(customer_name or user.name or "").strip() or None,
        origin="portal",
        company=company.strip(),
        phone=phone,
        amount=amount,
        fee=Decimal("0"),
        total=amount,
        payment_method="transfer",
        payment_status="pending",
        status="requested",
    )
    db.add(recarga)
    await db.commit()
    await db.refresh(recarga)
    return recarga


async def list_recargas_for_courier(db: AsyncSession, dp: DeliveryPerson, limit: int = 50):
    result = await db.execute(
        select(RecargaOrder)
        .where(RecargaOrder.delivery_person_id == dp.id)
        .order_by(RecargaOrder.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_recargas_for_user(db: AsyncSession, user_id, limit: int = 50):
    result = await db.execute(
        select(RecargaOrder)
        .where(RecargaOrder.user_id == user_id)
        .order_by(RecargaOrder.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_recarga(db: AsyncSession, recarga_id) -> RecargaOrder | None:
    return await db.get(RecargaOrder, recarga_id)


async def confirm_transfer_payment(db: AsyncSession, recarga: RecargaOrder) -> RecargaOrder:
    if recarga.payment_method != "transfer":
        raise ValueError("Esta recarga no es por transferencia")
    if recarga.payment_status == "paid":
        return recarga
    recarga.payment_status = "paid"
    recarga.paid_at = _now()
    if recarga.status == "requested":
        recarga.status = "pending"
    await db.commit()
    await db.refresh(recarga)
    return recarga


async def complete_recarga(
    db: AsyncSession,
    recarga: RecargaOrder,
    reference: str | None = None,
    notes: str | None = None,
) -> RecargaOrder:
    if recarga.status in ("completed", "refunded"):
        raise ValueError("La recarga ya está cerrada")
    recarga.status = "completed"
    recarga.completed_at = _now()
    recarga.provider_reference = (reference or "").strip() or recarga.provider_reference
    if notes:
        recarga.notes = notes
    if recarga.order_id:
        order = await db.get(Order, recarga.order_id)
        if order is not None and (order.recharge_amount or 0) > 0:
            order.recharge_status = "completed"
    await db.commit()
    await db.refresh(recarga)
    return recarga


async def fail_recarga(
    db: AsyncSession,
    recarga: RecargaOrder,
    dp: DeliveryPerson | None,
    *,
    refund: bool = True,
    error_message: str | None = None,
) -> RecargaOrder:
    if recarga.status == "completed":
        raise ValueError("La recarga ya se completó")
    if error_message:
        recarga.error_message = error_message
    if refund and recarga.payment_status == "paid":
        if dp is None and recarga.delivery_person_id:
            dp = await db.get(DeliveryPerson, recarga.delivery_person_id)
        if dp is not None:
            _reverse_cash_accounting(dp, recarga)
        recarga.payment_status = "refunded"
        recarga.refunded_at = _now()
        recarga.status = "refunded"
    else:
        recarga.status = "failed"
    await db.commit()
    await db.refresh(recarga)
    return recarga


async def retry_recarga(db: AsyncSession, recarga: RecargaOrder) -> RecargaOrder:
    if recarga.status not in ("failed",):
        raise ValueError("Solo se pueden reintentar recargas fallidas")
    if recarga.payment_status != "paid" and recarga.payment_method == "cash":
        raise ValueError("La recarga no tiene pago registrado")
    recarga.status = "pending"
    recarga.error_message = None
    await db.commit()
    await db.refresh(recarga)
    return recarga


# ---------------------------------------------------------------------------
# Recargas agregadas al pedido
# ---------------------------------------------------------------------------

def checkout_fee(payment_method: str, amount: Decimal) -> Decimal:
    """Comisión de $2 solo cuando la recarga del pedido se paga en efectivo."""
    if Decimal(amount or 0) <= 0:
        return Decimal("0.00")
    return CHECKOUT_RECHARGE_FEE if payment_method == "cash" else Decimal("0.00")


async def get_checkout_recarga(
    db: AsyncSession, order_id
) -> RecargaOrder | None:
    return await db.scalar(
        select(RecargaOrder).where(
            RecargaOrder.order_id == order_id,
            RecargaOrder.origin == "checkout",
        )
    )


async def confirm_checkout_recharge(
    db: AsyncSession, order
) -> RecargaOrder | None:
    """Marca como pagada la recarga del pedido al confirmarse la transferencia."""
    recarga = await get_checkout_recarga(db, order.id)
    if recarga is None:
        return None
    if recarga.payment_status != "paid":
        recarga.payment_status = "paid"
        recarga.paid_at = _now()
    return recarga


async def attach_courier(
    db: AsyncSession, order, delivery_person_id
) -> RecargaOrder | None:
    """Asocia la recarga del pedido al repartidor que lo entrega."""
    recarga = await get_checkout_recarga(db, order.id)
    if recarga is not None and recarga.delivery_person_id is None:
        recarga.delivery_person_id = delivery_person_id
    return recarga


async def charge_cancelled_checkout_recharge(
    db: AsyncSession, order
) -> Decimal:
    """Al cancelar un pedido en efectivo, la recarga ya aplicada queda a saldo."""
    amount = Decimal(order.recharge_amount or 0)
    if amount <= 0 or order.recharge_status == "charged":
        return Decimal("0.00")

    customer = await db.get(User, order.user_id) if order.user_id else None
    if customer is not None:
        customer.pending_balance = (customer.pending_balance or Decimal("0")) + amount
    order.recharge_status = "charged"
    recarga = await get_checkout_recarga(db, order.id)
    if recarga is not None:
        recarga.notes = (
            "Pedido cancelado: el monto de la recarga se cargó al saldo del cliente."
        )
    return amount


async def cancel_pending_checkout_recharge(
    db: AsyncSession, order, reason: str
) -> RecargaOrder | None:
    """Cancela la recarga si el pedido se cancela antes de pagarla."""
    recarga = await get_checkout_recarga(db, order.id)
    if recarga is None:
        return None
    if recarga.payment_status != "paid":
        recarga.status = "cancelled"
        recarga.payment_status = "cancelled"
        recarga.notes = reason
    return recarga


async def checkout_recharge_was_paid(db: AsyncSession, order) -> bool:
    recarga = await get_checkout_recarga(db, order.id)
    return bool(recarga and recarga.payment_status == "paid")
