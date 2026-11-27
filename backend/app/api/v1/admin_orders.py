"""Acciones del administrador sobre pedidos sin repartidor."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.user import User
from app.schemas.order import (
    AdminAssignCourierRequest,
    AdminOrderStatusUpdate,
    OrderOut,
)
from app.services import delivery_ops_service
from app.services.audit_service import log_action
from app.services.courier_limits import ensure_can_accept
from app.services.loyalty_service import award_on_delivery
from app.services.order_serialization import order_out
from app.services.push_service import (
    schedule_courier_assigned,
    schedule_new_order,
    schedule_order_status,
)

router = APIRouter()

ACTIVE_STATUSES = (
    "pending",
    "confirmed",
    "awaiting_courier",
    "preparing",
    "ready",
)
TERMINAL_STATUSES = ("delivered", "cancelled", "delivery_failed")


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


async def _load_order(db: AsyncSession, order_id: str) -> Order:
    result = await db.execute(
        select(Order)
        .where(Order.id == _uuid(order_id))
        .options(selectinload(Order.items))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return order


async def _out(db: AsyncSession, order: Order) -> OrderOut:
    customer = await db.get(User, order.user_id)
    return order_out(
        order,
        can_see_refund=True,
        customer_phone=customer.phone if customer else None,
    )


@router.get("/orders/courier-alerts")
async def courier_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    return await delivery_ops_service.courier_alert_rows(db)


@router.post("/orders/{order_id}/assign-courier", response_model=OrderOut)
async def assign_courier(
    order_id: str,
    body: AdminAssignCourierRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    order = await _load_order(db, order_id)
    if order.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="El pedido ya está cerrado")
    if order.delivery_person_id:
        raise HTTPException(status_code=400, detail="El pedido ya tiene repartidor")
    if order.delivery_mode != "platform" or order.admin_delivery:
        raise HTTPException(
            status_code=400, detail="Este pedido no se entrega con TuPedidoJR"
        )

    dp = await db.get(DeliveryPerson, body.courier_id)
    if not dp:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    user = await db.get(User, dp.user_id)
    if not user or not user.is_active or not dp.is_available:
        raise HTTPException(
            status_code=400, detail="El repartidor no está disponible"
        )
    await ensure_can_accept(db, dp)

    order.delivery_person_id = dp.id
    if order.status in ("pending", "awaiting_courier"):
        order.status = "preparing"
        if order.confirmed_at is None:
            order.confirmed_at = datetime.now(timezone.utc)
    order.no_courier_hold = False
    order.no_courier_decision_deadline = None
    order.courier_approval_deadline = None
    order.near_closing = False
    order.business_confirmation_deadline = None

    await log_action(
        db,
        current_user.id,
        "order.assign_courier",
        "order",
        order.id,
        {"courier_id": str(dp.id)},
    )
    await db.commit()
    await db.refresh(order)
    schedule_courier_assigned(str(order.id))
    schedule_new_order(str(order.id))
    return await _out(db, order)


@router.post("/orders/{order_id}/take-delivery", response_model=OrderOut)
async def take_delivery(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    order = await _load_order(db, order_id)
    if order.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="El pedido ya está cerrado")
    if order.delivery_mode != "platform":
        raise HTTPException(
            status_code=400, detail="Este pedido no es de TuPedidoJR"
        )
    if order.delivery_person_id:
        raise HTTPException(
            status_code=400, detail="El pedido ya tiene repartidor asignado"
        )

    order.admin_delivery = True
    order.admin_delivery_by = current_user.id
    order.delivery_earnings = Decimal("0")
    order.requires_courier_approval = False
    order.no_courier_hold = False
    order.no_courier_decision_deadline = None
    order.courier_approval_deadline = None
    order.near_closing = False
    order.business_confirmation_deadline = None
    if order.status in ("pending", "awaiting_courier"):
        order.status = "preparing"
        if order.confirmed_at is None:
            order.confirmed_at = datetime.now(timezone.utc)

    await log_action(
        db,
        current_user.id,
        "order.admin_delivery",
        "order",
        order.id,
        {"admin_id": str(current_user.id)},
    )
    await db.commit()
    await db.refresh(order)
    schedule_new_order(str(order.id))
    schedule_order_status(str(order.id), order.status)
    return await _out(db, order)


@router.post("/orders/{order_id}/status", response_model=OrderOut)
async def admin_order_status(
    order_id: str,
    body: AdminOrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    order = await _load_order(db, order_id)
    if not order.admin_delivery:
        raise HTTPException(
            status_code=400, detail="Este pedido no está asignado al admin"
        )
    if order.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="El pedido ya está cerrado")

    now = datetime.now(timezone.utc)
    if body.status == "picked_up":
        order.status = "in_delivery"
        order.picked_up_at = now
    else:
        order.status = "delivered"
        order.delivered_at = now
        if order.payment_method == "cash":
            order.payment_status = "approved"
        if order.courier_support_requested and (order.courier_support_fee or 0) > 0:
            order.restaurant_owes_platform = (
                order.restaurant_owes_platform or Decimal("0")
            ) + order.courier_support_fee
        await award_on_delivery(db, order)
        from app.services.cash_advance_service import (
            settle_restaurant_advances_for_order,
        )

        await settle_restaurant_advances_for_order(db, order)

    await log_action(
        db,
        current_user.id,
        "order.admin_status",
        "order",
        order.id,
        {"status": order.status},
    )
    await db.commit()
    await db.refresh(order)
    schedule_order_status(str(order.id), order.status)
    return await _out(db, order)


@router.post("/orders/{order_id}/switch-to-pickup", response_model=OrderOut)
async def switch_to_pickup(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    order = await _load_order(db, order_id)
    try:
        refund = await delivery_ops_service.switch_order_to_pickup(
            db, order, actor_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await log_action(
        db,
        current_user.id,
        "order.switch_to_pickup",
        "order",
        order.id,
        {"refund_amount": str(refund)},
    )
    await db.commit()
    await db.refresh(order)
    schedule_new_order(str(order.id))
    schedule_order_status(str(order.id), order.status)
    return await _out(db, order)
