"""Reglas de pedidos programados: fuera de horario y preparación anticipada."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.restaurant import Restaurant
from app.services.order_service import get_int_setting
from app.services.push_service import schedule_customer_early_prep


class ScheduledOrderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


async def enforce_scheduled_rules(
    db: AsyncSession,
    order: Order,
    restaurant: Restaurant,
    requested_status: str,
    *,
    accept_early_prep: bool = False,
) -> None:
    """Bloquea estados que no respetan la aprobación o la preparación anticipada."""
    if requested_status not in ("confirmed", "preparing", "ready"):
        return

    if (
        order.scheduled_outside_hours
        and order.scheduled_approval_status == "pending"
    ):
        raise ScheduledOrderError(
            "scheduled_approval_pending",
            "Primero confirma si aceptas el pedido programado fuera de horario.",
        )

    if requested_status not in ("preparing", "ready"):
        return
    if not order.scheduled_for or order.scheduled_prep_ack:
        return

    window_min = await get_int_setting(db, "SCHEDULED_PREP_WINDOW_MIN", 60)
    now = datetime.now(timezone.utc)
    scheduled = order.scheduled_for
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    if now >= scheduled - timedelta(minutes=max(window_min, 0)):
        return
    if restaurant.business_type != "restaurant":
        return
    if not accept_early_prep:
        raise ScheduledOrderError(
            "perishable_early_prep",
            (
                "Este pedido está programado para más tarde. En productos "
                "perecederos no es buena práctica prepararlo con tanta "
                "anticipación. ¿Aceptas prepararlo ahora o prefieres esperar?"
            ),
        )

    order.scheduled_prep_ack = True
    order.scheduled_prep_ack_at = now
    schedule_customer_early_prep(str(order.id))
