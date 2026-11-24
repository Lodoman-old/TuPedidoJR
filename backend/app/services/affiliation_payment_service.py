"""Planes de afiliación prepagados con validación de comprobantes."""
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

PLAN_DAYS = {1: 30, 3: 90, 6: 180, 12: 365}
PLAN_LABELS = {
    1: "1 mes",
    3: "3 meses",
    6: "6 meses",
    12: "12 meses",
}
PLAN_DEFAULTS = {
    1: "60.0",
    3: "160.0",
    6: "290.0",
    12: "500.0",
}


def _today() -> date:
    return datetime.now(LOCAL_TZ).date()


def plan_days(months: int) -> int:
    return PLAN_DAYS.get(int(months or 12), 365)


async def affiliation_price(db, months: int = 12) -> Decimal:
    months = int(months or 12)
    if months == 12:
        key = "AFFILIATION_ANNUAL_FEE"
    else:
        key = f"AFFILIATION_PRICE_{months}"
    raw = await get_setting_value(db, key, PLAN_DEFAULTS.get(months, "500.0"))
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(PLAN_DEFAULTS.get(months, "500.0"))


async def affiliation_fee(db) -> Decimal:
    return await affiliation_price(db, 12)


async def affiliation_plans(db) -> list[dict]:
    plans = []
    for months in (1, 3, 6, 12):
        price = await affiliation_price(db, months)
        plans.append({
            "months": months,
            "label": PLAN_LABELS[months],
            "price": str(price),
            "days": plan_days(months),
            "physical": months == 12,
        })
    return plans


async def _run_validation(restaurant_id: str, proof_url: str, months: int) -> None:
    months = int(months or 12)
    async with async_session() as db:
        restaurant = await db.get(Restaurant, restaurant_id)
        if not restaurant:
            return
        amount = await affiliation_price(db, months)
        try:
            record = await create_and_validate(
                db,
                "affiliation_payment",
                restaurant.id,
                proof_url,
                TRANSFER,
                amount,
                datetime.now(timezone.utc),
                plan_months=months,
            )
        except Exception:
            logger.exception("No se pudo validar la afiliación de %s", restaurant_id)
            return
        if record is None or record.status not in ("high", "preapproved"):
            return

        previous = restaurant.affiliation_expires_at
        base = _today()
        if previous and previous >= base:
            base = previous
        restaurant.affiliation_expires_at = base + timedelta(days=plan_days(months))
        restaurant.affiliation_reminder_on = None
        record.extracted = {
            **(record.extracted or {}),
            "previous_expires_at": previous.isoformat() if previous else None,
            "applied": True,
            "applied_months": months,
        }
        await db.commit()


def schedule_affiliation_validation(
    restaurant_id: str,
    proof_url: str,
    months: int = 12,
) -> None:
    try:
        asyncio.create_task(_run_validation(str(restaurant_id), proof_url, int(months or 12)))
    except RuntimeError:
        logger.debug("No event loop for affiliation validation")
