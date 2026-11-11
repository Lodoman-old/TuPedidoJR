"""Cancellation and refund business rules.

Policy (all values configurable from ``settings``):

* The customer can always cancel while the order is ``pending`` (the
  restaurant has not accepted it yet).
* After the restaurant confirms, the customer has ``CANCELLATION_WINDOW_MIN``
  minutes to cancel.
* The restaurant can cancel while the order is pending, confirmed, preparing
  or ready (never after the courier picked it up).
* A superuser can cancel any order that is not already delivered/cancelled.
* Cash orders never generate a refund. Paid online orders generate a pending
  refund when ``CANCELLATION_REFUND_ENABLED`` is on.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coupon import Coupon
from app.models.order import Order
from app.services.order_service import get_setting_value

CUSTOMER_DEFAULT_STATUSES = ["pending", "confirmed"]
RESTAURANT_DEFAULT_STATUSES = ["pending", "confirmed", "preparing", "ready"]

STATUS_LABELS = {
    "pending": "pendiente",
    "confirmed": "confirmado",
    "preparing": "en preparación",
    "ready": "listo",
    "in_delivery": "en reparto",
    "picked_up": "recogido",
    "delivered": "entregado",
    "cancelled": "cancelado",
}


async def get_policy(db: AsyncSession) -> dict:
    try:
        window = int(await get_setting_value(db, "CANCELLATION_WINDOW_MIN", "5") or 5)
    except (TypeError, ValueError):
        window = 5
    refund_enabled = (
        await get_setting_value(db, "CANCELLATION_REFUND_ENABLED", "true")
    ).lower() == "true"
    return {
        "customer_allowed_statuses": CUSTOMER_DEFAULT_STATUSES,
        "restaurant_allowed_statuses": RESTAURANT_DEFAULT_STATUSES,
        "window_min": max(window, 0),
        "refund_enabled": refund_enabled,
        "customer_message": (
            "Puedes cancelar sin costo mientras el restaurante no acepte el pedido. "
            f"Después de confirmado tienes {max(window, 0)} minutos."
        ),
    }


def _check_window(order: Order, window_min: int, now: datetime) -> bool:
    if window_min <= 0:
        return False
    reference = order.confirmed_at or order.placed_at
    if reference is None:
        return False
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return now - reference <= timedelta(minutes=window_min)


def can_cancel(order: Order, role: str, window_min: int, now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    status = order.status

    if status in ("delivered", "cancelled"):
        return False, "El pedido ya no se puede cancelar"

    if role == "admin":
        return True, ""

    if role == "restaurant":
        if status in RESTAURANT_DEFAULT_STATUSES:
            return True, ""
        return False, (
            f"El pedido está {STATUS_LABELS.get(status, status)} y ya no puede "
            "cancelarse desde el restaurante"
        )

    # Customer
    if status == "pending":
        return True, ""
    if status == "confirmed":
        if _check_window(order, window_min, now):
            return True, ""
        return False, (
            "El pedido ya fue confirmado y pasó el tiempo de cancelación. "
            "Contacta al restaurante para más ayuda."
        )
    return False, (
        f"El pedido está {STATUS_LABELS.get(status, status)} y ya no puede cancelarse. "
        "Contacta al restaurante para más ayuda."
    )


async def build_refund(db: AsyncSession, order: Order) -> tuple[Decimal, str, str]:
    """Return ``(refund_amount, refund_status, payment_status)``."""
    refund_enabled = (
        await get_setting_value(db, "CANCELLATION_REFUND_ENABLED", "true")
    ).lower() == "true"
    total = Decimal(order.total or 0)

    if order.payment_method == "cash":
        return Decimal("0.00"), "not_required", "cancelled"

    if order.payment_status == "refunded":
        return total, "refunded", "refunded"

    if order.payment_status in ("approved", "paid"):
        if refund_enabled:
            # MP/transfer refunds are processed manually for now (gateways are
            # disabled), so the order is flagged as pending refund.
            return total, "pending", order.payment_status
        return Decimal("0.00"), "not_required", order.payment_status

    return Decimal("0.00"), "not_required", "cancelled"


async def apply_cancellation(
    db: AsyncSession,
    order: Order,
    actor_id,
    role: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Validate and apply a cancellation. Raises ``ValueError`` if not allowed."""
    policy = await get_policy(db)
    allowed, message = can_cancel(order, role, policy["window_min"], now)
    if not allowed:
        raise ValueError(message)

    refund_amount, refund_status, payment_status = await build_refund(db, order)
    now = now or datetime.now(timezone.utc)

    order.status = "cancelled"
    order.cancelled_at = now
    order.cancelled_by = actor_id
    order.cancellation_reason = (reason or "").strip() or None
    order.refund_amount = refund_amount
    order.refund_status = refund_status
    order.payment_status = payment_status

    if order.coupon_id:
        result = await db.execute(select(Coupon).where(Coupon.id == order.coupon_id))
        coupon = result.scalar_one_or_none()
        if coupon and coupon.current_uses and coupon.current_uses > 0:
            coupon.current_uses -= 1

    if order.points_redeemed:
        from app.models.user import User

        result = await db.execute(select(User).where(User.id == order.user_id))
        customer = result.scalar_one_or_none()
        if customer:
            customer.loyalty_points = int(customer.loyalty_points or 0) + int(order.points_redeemed)

    if order.delivery_person_id:
        from app.models.delivery_person import DeliveryPerson

        result = await db.execute(
            select(DeliveryPerson).where(DeliveryPerson.id == order.delivery_person_id)
        )
        courier = result.scalar_one_or_none()
        if courier and courier.current_order_id == order.id:
            courier.current_order_id = None

    return {
        "refund_amount": refund_amount,
        "refund_status": refund_status,
        "payment_status": payment_status,
    }
