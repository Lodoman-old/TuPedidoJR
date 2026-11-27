"""Disponibilidad real de repartidores para el flujo de pedidos."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery_person import DeliveryPerson
from app.models.user import User
from app.services.courier_limits import active_service_count, service_limits


async def available_couriers(db: AsyncSession) -> list[dict]:
    """Repartidores activos, disponibles y con cupo para otro servicio."""
    max_services, _warn = await service_limits(db)
    rows = (
        await db.execute(
            select(DeliveryPerson, User)
            .join(User, User.id == DeliveryPerson.user_id)
            .where(
                DeliveryPerson.is_available.is_(True),
                User.is_active.is_(True),
            )
            .order_by(User.name)
        )
    ).all()

    result: list[dict] = []
    for dp, user in rows:
        count = await active_service_count(db, dp.id)
        if count >= max_services:
            continue
        result.append(
            {
                "id": str(dp.id),
                "user_id": str(dp.user_id),
                "name": user.name or user.email,
                "phone": user.phone,
                "vehicle_type": dp.vehicle_type,
                "active_services": count,
            }
        )
    return result


async def available_courier_count(db: AsyncSession) -> int:
    return len(await available_couriers(db))


async def courier_availability_for_order(
    db: AsyncSession, delivery_mode: str
) -> dict:
    if delivery_mode != "platform":
        return {"enabled": False, "available": 0}
    return {
        "enabled": True,
        "available": await available_courier_count(db),
    }
