"""Alertas y cancelaciones del flujo de pedidos sin repartidor."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.services.cancellation_service import apply_cancellation
from app.services.order_service import delivery_ops_v2_enabled, get_int_setting
from app.services.push_service import (
    schedule_admin_no_courier,
    schedule_business_courier_support_waiting,
    schedule_customer_no_courier_decision,
    schedule_customer_near_closing_cancelled,
    schedule_customer_scheduled_rejected,
    schedule_order_status,
    schedule_scheduled_reminder,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def switch_order_to_pickup(
    db: AsyncSession, order: Order, *, actor_id=None
) -> Decimal:
    """Cambia un pedido a recoger y devuelve el envío si ya estaba pagado."""
    if order.status in ("delivered", "cancelled", "delivery_failed"):
        raise ValueError("El pedido ya está cerrado")
    if order.status in ("in_delivery", "picked_up"):
        raise ValueError("El pedido ya está en reparto")
    if order.fulfillment_type == "pickup":
        return Decimal("0")

    old_fee = Decimal(order.delivery_fee or 0)
    was_paid = (
        order.payment_method == "transfer"
        and order.payment_status in ("approved", "paid")
    )
    order.fulfillment_type = "pickup"
    order.delivery_mode = "pickup"
    restaurant = await db.get(Restaurant, order.restaurant_id)
    if restaurant is not None:
        order.delivery_address = f"{restaurant.name} — {restaurant.address}"
    order.delivery_fee = Decimal("0")
    order.total = max(Decimal(order.total or 0) - old_fee, Decimal("0"))
    order.requires_courier_approval = False
    order.no_courier_hold = False
    order.no_courier_decision_deadline = None
    order.courier_approval_deadline = None
    order.near_closing = False
    order.business_confirmation_deadline = None
    order.admin_delivery = False
    order.admin_delivery_by = None
    if order.status in ("awaiting_courier", "pending"):
        order.status = "pending"
    if was_paid and old_fee > 0:
        order.refund_amount = old_fee
        order.refund_status = "pending"
    return old_fee


async def _alert_prepared_without_courier(db: AsyncSession) -> int:
    """Avisa al admin cuando un pedido ya listo sigue sin repartidor."""
    now = _now()
    minutes = await get_int_setting(db, "COURIER_ALERT_MIN", 15)
    if minutes <= 0:
        return 0
    cutoff = now - timedelta(minutes=minutes)
    rows = (
        await db.execute(
            select(Order).where(
                Order.delivery_mode == "platform",
                Order.delivery_person_id.is_(None),
                Order.admin_delivery.is_(False),
                Order.courier_alert_at.is_(None),
                Order.status.in_(("preparing", "ready")),
                or_(
                    and_(
                        Order.status == "ready",
                        Order.ready_at.is_not(None),
                        Order.ready_at <= cutoff,
                    ),
                    and_(
                        Order.status == "preparing",
                        Order.confirmed_at.is_not(None),
                        Order.confirmed_at <= cutoff,
                    ),
                ),
            )
        )
    ).scalars().all()
    for order in rows:
        order.courier_alert_at = now
        await db.commit()
        schedule_admin_no_courier(str(order.id), minutes)
    return len(rows)


async def _notify_no_courier_wait(db: AsyncSession) -> int:
    """Al agotarse la espera, avisa al cliente para que decida."""
    now = _now()
    rows = (
        await db.execute(
            select(Order).where(
                Order.no_courier_hold.is_(True),
                Order.delivery_person_id.is_(None),
                Order.no_courier_notified_at.is_(None),
                Order.courier_approval_deadline.is_not(None),
                Order.courier_approval_deadline <= now,
                Order.status.notin_(("delivered", "cancelled", "delivery_failed")),
            )
        )
    ).scalars().all()
    for order in rows:
        decision_min = await get_int_setting(db, "NO_COURIER_DECISION_MIN", 15)
        order.no_courier_notified_at = now
        order.no_courier_decision_deadline = now + timedelta(
            minutes=max(decision_min, 1)
        )
        await db.commit()
        schedule_customer_no_courier_decision(str(order.id))
    return len(rows)


async def _cancel_unresolved_no_courier(db: AsyncSession) -> int:
    """Cancela pedidos cuyo cliente no eligió recoger ni cancelar."""
    now = _now()
    rows = (
        await db.execute(
            select(Order).where(
                Order.no_courier_hold.is_(True),
                Order.delivery_person_id.is_(None),
                Order.no_courier_decision_deadline.is_not(None),
                Order.no_courier_decision_deadline <= now,
                Order.status.notin_(("delivered", "cancelled", "delivery_failed")),
            )
        )
    ).scalars().all()
    cancelled = 0
    for order in rows:
        try:
            await apply_cancellation(
                db,
                order,
                actor_id=None,
                role="admin",
                reason="Sin repartidor después del tiempo de espera.",
                now=now,
            )
            await db.commit()
            schedule_order_status(str(order.id), "cancelled")
            cancelled += 1
        except Exception:
            await db.rollback()
            logger.exception("No se pudo cancelar el pedido %s", order.id)
    return cancelled


async def _cancel_near_closing_without_response(db: AsyncSession) -> int:
    """Cancela pedidos cerca del cierre que el negocio no aceptó a tiempo."""
    now = _now()
    rows = (
        await db.execute(
            select(Order).where(
                Order.near_closing.is_(True),
                Order.business_confirmation_deadline.is_not(None),
                Order.business_confirmation_deadline <= now,
                Order.status.notin_(("preparing", "ready", "picked_up", "delivered", "cancelled")),
            )
        )
    ).scalars().all()
    cancelled = 0
    for order in rows:
        try:
            await apply_cancellation(
                db,
                order,
                actor_id=None,
                role="admin",
                reason="El negocio no aceptó el pedido cerca del cierre.",
                now=now,
            )
            await db.commit()
            schedule_order_status(str(order.id), "cancelled")
            schedule_customer_near_closing_cancelled(str(order.id))
            cancelled += 1
        except Exception:
            await db.rollback()
            logger.exception("No se pudo cancelar el pedido %s", order.id)
    return cancelled


async def courier_alert_orders(
    db: AsyncSession, limit: int = 50
) -> list[Order]:
    """Pedidos sin repartidor que el admin debe atender."""
    now = _now()
    minutes = await get_int_setting(db, "COURIER_ALERT_MIN", 15)
    cutoff = now - timedelta(minutes=max(minutes, 1))
    rows = (
        await db.execute(
            select(Order)
            .where(
                Order.delivery_mode == "platform",
                Order.delivery_person_id.is_(None),
                Order.status.in_(
                    (
                        "pending",
                        "confirmed",
                        "awaiting_courier",
                        "preparing",
                        "ready",
                        "in_delivery",
                        "picked_up",
                    )
                ),
                or_(
                    Order.courier_alert_at.is_not(None),
                    Order.no_courier_hold.is_(True),
                    Order.admin_delivery.is_(True),
                    Order.courier_support_requested.is_(True),
                    and_(
                        Order.status == "ready",
                        Order.ready_at.is_not(None),
                        Order.ready_at <= cutoff,
                    ),
                    and_(
                        Order.status == "preparing",
                        Order.confirmed_at.is_not(None),
                        Order.confirmed_at <= cutoff,
                    ),
                ),
            )
            .order_by(Order.placed_at)
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def courier_alert_rows(
    db: AsyncSession, limit: int = 50
) -> list[dict]:
    now = _now()
    orders = await courier_alert_orders(db, limit)
    rows = []
    for order in orders:
        restaurant = await db.get(Restaurant, order.restaurant_id)
        reference = order.ready_at or order.confirmed_at or order.placed_at
        minutes = (
            int((now - reference).total_seconds() // 60)
            if reference
            else 0
        )
        rows.append(
            {
                "id": str(order.id),
                "short": str(order.id)[:8].upper(),
                "restaurant_name": restaurant.name if restaurant else "Negocio",
                "restaurant_id": str(order.restaurant_id),
                "status": order.status,
                "minutes": max(minutes, 0),
                "total": str(order.total or 0),
                "no_courier_hold": bool(order.no_courier_hold),
                "admin_delivery": bool(order.admin_delivery),
            }
        )
    return rows


async def _process_delivery_ops(db: AsyncSession) -> dict:
    if not await delivery_ops_v2_enabled(db):
        return {"enabled": False}
    alerts = await _alert_prepared_without_courier(db)
    waits = await _notify_no_courier_wait(db)
    cancelled = await _cancel_unresolved_no_courier(db)
    near_closing = await _cancel_near_closing_without_response(db)
    reminders = await _remind_scheduled_orders(db)
    scheduled_cancelled = await _cancel_scheduled_outside_hours(db)
    support_alerts = await _alert_courier_support_waiting(db)
    return {
        "enabled": True,
        "alerts": alerts,
        "waits": waits,
        "cancelled": cancelled,
        "near_closing": near_closing,
        "reminders": reminders,
        "scheduled_cancelled": scheduled_cancelled,
        "support_alerts": support_alerts,
    }


async def _remind_scheduled_orders(db: AsyncSession) -> int:
    """Avisa al negocio cuando falta poco para un pedido programado."""
    now = _now()
    minutes = await get_int_setting(db, "SCHEDULED_REMINDER_MIN", 60)
    if minutes <= 0:
        return 0
    cutoff = now + timedelta(minutes=minutes)
    rows = (
        await db.execute(
            select(Order).where(
                Order.scheduled_for.is_not(None),
                Order.scheduled_for <= cutoff,
                Order.scheduled_reminder_sent_at.is_(None),
                Order.status.notin_(("delivered", "cancelled", "delivery_failed")),
            )
        )
    ).scalars().all()
    for order in rows:
        order.scheduled_reminder_sent_at = now
        await db.commit()
        schedule_scheduled_reminder(str(order.id), minutes)
    return len(rows)


async def _cancel_scheduled_outside_hours(db: AsyncSession) -> int:
    now = _now()
    rows = (
        await db.execute(
            select(Order).where(
                Order.scheduled_outside_hours.is_(True),
                Order.scheduled_approval_status == "pending",
                Order.scheduled_approval_deadline.is_not(None),
                Order.scheduled_approval_deadline <= now,
                Order.status.notin_(("delivered", "cancelled", "delivery_failed")),
            )
        )
    ).scalars().all()
    cancelled = 0
    for order in rows:
        try:
            await apply_cancellation(
                db,
                order,
                actor_id=None,
                role="admin",
                reason="El negocio no aceptó el pedido programado fuera de horario.",
                now=now,
            )
            order.scheduled_approval_status = "rejected"
            await db.commit()
            schedule_order_status(str(order.id), "cancelled")
            schedule_customer_scheduled_rejected(str(order.id))
            cancelled += 1
        except Exception:
            await db.rollback()
            logger.exception("No se pudo cancelar el pedido programado %s", order.id)
    return cancelled


async def _alert_courier_support_waiting(db: AsyncSession) -> int:
    now = _now()
    minutes = await get_int_setting(db, "COURIER_SUPPORT_ALERT_MIN", 15)
    if minutes <= 0:
        return 0
    cutoff = now - timedelta(minutes=minutes)
    rows = (
        await db.execute(
            select(Order).where(
                Order.courier_support_requested.is_(True),
                Order.delivery_person_id.is_(None),
                Order.admin_delivery.is_(False),
                Order.courier_support_alert_at.is_(None),
                Order.courier_support_requested_at.is_not(None),
                Order.courier_support_requested_at <= cutoff,
                Order.status.notin_(("delivered", "cancelled", "delivery_failed")),
            )
        )
    ).scalars().all()
    for order in rows:
        order.courier_support_alert_at = now
        await db.commit()
        schedule_business_courier_support_waiting(str(order.id), minutes)
    return len(rows)


async def process_delivery_ops(db: AsyncSession | None = None) -> dict:
    if db is not None:
        return await _process_delivery_ops(db)
    async with async_session() as session:
        return await _process_delivery_ops(session)


async def delivery_ops_loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            await process_delivery_ops()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error en el loop de operación de reparto")
        await asyncio.sleep(interval_seconds)
