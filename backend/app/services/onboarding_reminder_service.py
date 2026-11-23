"""Recordatorios de onboarding a los 2 y 7 días."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.restaurant import Restaurant
from app.services.email_service import send_onboarding_reminder
from app.services.onboarding_service import business_onboarding

logger = logging.getLogger(__name__)


async def _owner_contacts(db: AsyncSession, restaurant_id) -> list[tuple[str, str]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT u.email, u.name
                FROM users u
                JOIN restaurant_users ru ON ru.user_id = u.id
                WHERE ru.restaurant_id = :rid
                  AND ru.is_active = true
                  AND ru.role IN ('owner', 'manager')
                  AND u.is_active = true
                  AND u.email IS NOT NULL
                """
            ),
            {"rid": restaurant_id},
        )
    ).all()
    contacts = {(row[0], row[1] or "") for row in rows if row[0]}
    if not contacts:
        row = (
            await db.execute(
                text(
                    """
                    SELECT u.email, u.name
                    FROM users u
                    JOIN restaurants r ON r.owner_id = u.id
                    WHERE r.id = :rid
                      AND u.is_active = true
                      AND u.email IS NOT NULL
                    """
                ),
                {"rid": restaurant_id},
            )
        ).first()
        if row and row[0]:
            contacts.add((row[0], row[1] or ""))
    return sorted(contacts)


async def send_due_onboarding_reminders(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    two_days_ago = now - timedelta(days=2)
    seven_days_ago = now - timedelta(days=7)
    sent = {"two_day": 0, "seven_day": 0, "skipped": 0}

    result = await db.execute(
        select(Restaurant).where(Restaurant.status == "active")
    )
    for restaurant in result.scalars().all():
        reference = restaurant.approved_at or restaurant.created_at
        if reference is None or reference > two_days_ago:
            continue

        data = await business_onboarding(db, restaurant)
        missing = [item for item in data["items"] if not item["done"]]
        if not missing:
            sent["skipped"] += 1
            continue

        is_seven = reference <= seven_days_ago
        if is_seven and restaurant.onboarding_reminder_7_at is None:
            kind = "seven_day"
        elif not is_seven and restaurant.onboarding_reminder_2_at is None:
            kind = "two_day"
        else:
            sent["skipped"] += 1
            continue

        contacts = await _owner_contacts(db, restaurant.id)
        if not contacts:
            sent["skipped"] += 1
            continue

        ok_all = True
        for email, name in contacts:
            try:
                ok, _detail = await send_onboarding_reminder(
                    db,
                    email,
                    name or "equipo",
                    restaurant.name,
                    str(restaurant.id),
                    missing,
                    final=is_seven,
                )
            except Exception:
                logger.exception(
                    "No se pudo enviar recordatorio de onboarding a %s", email
                )
                ok = False
            ok_all = ok_all and ok

        if not ok_all:
            sent["skipped"] += 1
            continue

        if is_seven:
            restaurant.onboarding_reminder_7_at = now
            if restaurant.onboarding_reminder_2_at is None:
                restaurant.onboarding_reminder_2_at = now
            sent["seven_day"] += 1
        else:
            restaurant.onboarding_reminder_2_at = now
            sent["two_day"] += 1
        await db.commit()

    return sent


async def onboarding_reminder_loop(interval_seconds: int = 6 * 3600) -> None:
    while True:
        try:
            async with async_session() as db:
                result = await send_due_onboarding_reminders(db)
                if result["two_day"] or result["seven_day"]:
                    logger.info("Recordatorios de onboarding enviados: %s", result)
        except Exception:
            logger.exception("No se pudieron enviar los recordatorios de onboarding")
        await asyncio.sleep(interval_seconds)
