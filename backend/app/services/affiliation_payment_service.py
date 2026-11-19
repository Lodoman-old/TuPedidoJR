"""Pago de la afiliación anual por transferencia con validación de IA."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from app.db.session import async_session
from app.models.restaurant import Restaurant
from app.services.receipt_validation_service import TRANSFER, create_and_validate
from app.services.order_service import get_setting_value

logger = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("America/Mexico_City")


def _today() -> date:
    return datetime.now(LOCAL_TZ).date()


async def affiliation_fee(db) -> Decimal:
    raw = await get_setting_value(db, "AFFILIATION_ANNUAL_FEE", "500.0")
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("500.0")


async def _run_validation(restaurant_id: str, proof_url: str) -> None:
    async with async_session() as db:
        restaurant = await db.get(Restaurant, restaurant_id)
        if not restaurant:
            return
        amount = await affiliation_fee(db)
        try:
            record = await create_and_validate(
                db,
                "affiliation_payment",
                restaurant.id,
                proof_url,
                TRANSFER,
                amount,
                datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("No se pudo validar la afiliación de %s", restaurant_id)
            return
        if record is None or record.status != "high":
            return

        previous = restaurant.affiliation_expires_at
        base = _today()
        if previous and previous >= base:
            base = previous
        restaurant.affiliation_expires_at = base + timedelta(days=365)
        restaurant.affiliation_reminder_on = None
        record.extracted = {
            **(record.extracted or {}),
            "previous_expires_at": previous.isoformat() if previous else None,
            "applied": True,
        }
        await db.commit()


def schedule_affiliation_validation(restaurant_id: str, proof_url: str) -> None:
    try:
        asyncio.create_task(_run_validation(str(restaurant_id), proof_url))
    except RuntimeError:
        logger.debug("No event loop for affiliation validation")
