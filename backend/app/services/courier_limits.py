"""Límites de servicios simultáneos por repartidor.

Un "servicio activo" es cualquier pedido, mandado o envío asignado al
repartidor que todavía no termina. El límite y el umbral de aviso se
configuran desde Admin -> Configuración.
"""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mandado import Mandado
from app.models.order import Order
from app.models.shipment import Shipment
from app.services.order_service import get_setting_value

DEFAULT_MAX_SERVICES = 5
DEFAULT_WARN_SERVICES = 4


async def service_limits(db: AsyncSession) -> tuple[int, int]:
    """Devuelve ``(máximo, aviso)`` saneados."""
    try:
        max_services = int(await get_setting_value(db, "MAX_ACTIVE_SERVICES", str(DEFAULT_MAX_SERVICES)))
    except (TypeError, ValueError):
        max_services = DEFAULT_MAX_SERVICES
    try:
        warn_services = int(await get_setting_value(db, "WARN_ACTIVE_SERVICES", str(DEFAULT_WARN_SERVICES)))
    except (TypeError, ValueError):
        warn_services = DEFAULT_WARN_SERVICES
    max_services = max(1, max_services)
    warn_services = min(max(0, warn_services), max_services - 1) if max_services > 1 else 0
    return max_services, warn_services


async def active_service_count(db: AsyncSession, delivery_person_id) -> int:
    orders = await db.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.delivery_person_id == delivery_person_id,
            Order.status.notin_(("delivered", "cancelled", "delivery_failed")),
        )
    )
    mandados = await db.scalar(
        select(func.count())
        .select_from(Mandado)
        .where(
            Mandado.delivery_person_id == delivery_person_id,
            Mandado.status.notin_(("completed", "cancelled", "delivery_failed")),
        )
    )
    shipments = await db.scalar(
        select(func.count())
        .select_from(Shipment)
        .where(
            Shipment.delivery_person_id == delivery_person_id,
            Shipment.status.notin_(("delivered", "failed", "cancelled")),
        )
    )
    return int(orders or 0) + int(mandados or 0) + int(shipments or 0)


async def ensure_can_accept(db: AsyncSession, dp) -> None:
    """Bloquea la aceptación si el repartidor ya llegó al límite."""
    count = await active_service_count(db, dp.id)
    max_services, _warn = await service_limits(db)
    if count >= max_services:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ya tienes {count} servicios activos. "
                f"El límite es {max_services}. Termina uno antes de aceptar otro."
            ),
        )
