"""Recordatorios de afiliación anual de los restaurantes."""
import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.restaurant import Restaurant
from app.services.push_service import send_to_user

logger = logging.getLogger(__name__)

REMINDER_DAYS = 10


async def _send_reminders(db: AsyncSession) -> int:
    today = date.today()
    limit = today + timedelta(days=REMINDER_DAYS)
    sent = 0
    result = await db.execute(
        select(Restaurant).where(
            Restaurant.status == "active",
            Restaurant.affiliation_expires_at.is_not(None),
            Restaurant.affiliation_expires_at >= today,
            Restaurant.affiliation_expires_at <= limit,
        )
    )
    restaurants = result.scalars().all()
    for restaurant in restaurants:
        if restaurant.affiliation_reminder_on == today:
            continue
        days_left = (restaurant.affiliation_expires_at - today).days
        if days_left <= 0:
            body = (
                f"{restaurant.name}: tu afiliación vence hoy. "
                "Renueva para seguir apareciendo en los listados."
            )
        else:
            body = (
                f"{restaurant.name}: tu afiliación vence en {days_left} día(s). "
                "Renueva para seguir apareciendo en los listados."
            )
        try:
            await send_to_user(
                db,
                restaurant.owner_id,
                "Tu afiliación está por vencer",
                body,
                {"type": "affiliation", "restaurant_id": str(restaurant.id)},
                "amber",
            )
        except Exception:
            logger.exception(
                "No se pudo enviar el recordatorio de afiliación a %s",
                restaurant.id,
            )
            continue
        restaurant.affiliation_reminder_on = today
        sent += 1
    await db.commit()
    if sent:
        logger.info("Recordatorios de afiliación enviados: %s", sent)
    return sent


async def send_affiliation_reminders(db: AsyncSession | None = None) -> int:
    """Avisa a los dueños cuyo pago vence en 10 días o menos (una vez al día)."""
    if db is not None:
        return await _send_reminders(db)
    async with async_session() as session:
        return await _send_reminders(session)


async def affiliation_reminder_loop(interval_seconds: int = 6 * 3600) -> None:
    """Revisa varias veces al día; el envío real ocurre una vez por día."""
    while True:
        try:
            await send_affiliation_reminders()
        except Exception:
            logger.exception("Falló la revisión de afiliaciones")
        await asyncio.sleep(interval_seconds)
