"""Cancela pedidos lejanos que no consiguieron repartidor a tiempo."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.order import Order
from app.services.cancellation_service import apply_cancellation
from app.services.push_service import schedule_order_status

logger = logging.getLogger(__name__)

REASON = "Ningún repartidor aceptó el pedido a tiempo"


async def _cancel_expired(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Order)
        .where(
            Order.requires_courier_approval.is_(True),
            Order.status.in_(["pending", "confirmed", "awaiting_courier"]),
            Order.delivery_person_id.is_(None),
            Order.courier_approval_deadline.is_not(None),
            Order.courier_approval_deadline <= now,
        )
        .with_for_update(skip_locked=True)
    )
    orders = list(result.scalars().all())
    cancelled = 0
    for order in orders:
        if order.status not in ("pending", "confirmed", "awaiting_courier"):
            continue
        if order.delivery_person_id:
            continue
        try:
            await apply_cancellation(
                db,
                order,
                actor_id=None,
                role="admin",
                reason=REASON,
                now=now,
            )
            cancelled += 1
        except Exception:
            logger.exception("No se pudo cancelar el pedido lejano %s", order.id)
    await db.commit()
    for order in orders:
        if order.status == "cancelled":
            schedule_order_status(str(order.id), "cancelled")
    if cancelled:
        logger.info("Pedidos lejanos cancelados por falta de repartidor: %s", cancelled)
    return cancelled


async def cancel_expired_awaiting_orders(db: AsyncSession | None = None) -> int:
    if db is not None:
        return await _cancel_expired(db)
    async with async_session() as session:
        return await _cancel_expired(session)


async def courier_timeout_loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            await cancel_expired_awaiting_orders()
        except Exception:
            logger.exception("Falló la cancelación automática de pedidos lejanos")
        await asyncio.sleep(interval_seconds)
