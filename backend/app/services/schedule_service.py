"""Opening-hours logic for restaurants.

A restaurant can define a weekly schedule. If it has no rows at all, the
manual ``Restaurant.is_open`` switch is used (backwards compatible). If the
manual switch is off, the restaurant is always considered closed.
"""
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.restaurant import Restaurant
from app.models.restaurant_schedule import RestaurantSchedule
from app.services.order_service import get_setting_value

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/Mexico_City"
WEEKDAY_LABELS = [
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
]


def _to_time(value) -> time:
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _format_time(value) -> str:
    return _to_time(value).strftime("%H:%M")


def _in_range(moment: time, start: time, end: time) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= moment <= end
    # Overnight shift, e.g. 20:00-02:00.
    return moment >= start or moment <= end


def _evaluate(schedules: list[RestaurantSchedule], now: datetime) -> dict:
    """Pure evaluation of a weekly schedule at ``now``."""
    if not schedules:
        return {"is_open": None, "message": "", "next_open": None, "next_open_offset": None}

    today = now.weekday()
    current = now.time()

    for row in schedules:
        if row.day_of_week != today or row.is_closed:
            continue
        start, end = _to_time(row.open_time), _to_time(row.close_time)
        if _in_range(current, start, end):
            return {
                "is_open": True,
                "message": f"Abierto ahora, cierra a las {_format_time(row.close_time)}",
                "next_open": None,
                "next_open_offset": None,
            }

    # Overnight shift that started yesterday.
    yesterday = (today - 1) % 7
    for row in schedules:
        if row.day_of_week != yesterday or row.is_closed:
            continue
        start, end = _to_time(row.open_time), _to_time(row.close_time)
        if start > end and current <= end:
            return {
                "is_open": True,
                "message": f"Abierto ahora, cierra a las {_format_time(row.close_time)}",
                "next_open": None,
                "next_open_offset": None,
            }

    next_open = None
    next_label = None
    next_offset = None
    for offset in range(0, 8):
        day = (today + offset) % 7
        day_rows = [
            row for row in schedules
            if row.day_of_week == day and not row.is_closed
        ]
        if not day_rows:
            continue
        for row in sorted(day_rows, key=lambda r: _to_time(r.open_time)):
            start = _to_time(row.open_time)
            if offset == 0 and start <= current:
                continue
            next_open = start
            next_offset = offset
            next_label = "hoy" if offset == 0 else ("mañana" if offset == 1 else WEEKDAY_LABELS[day])
            break
        if next_open is not None:
            break

    if next_open is not None:
        message = f"Cerrado. Abre {next_label} a las {next_open.strftime('%H:%M')}"
    else:
        message = "Cerrado. Sin horario configurado"
    return {
        "is_open": False,
        "message": message,
        "next_open": next_open,
        "next_open_offset": next_offset,
    }


async def get_schedules(db: AsyncSession, restaurant_id) -> list[RestaurantSchedule]:
    result = await db.execute(
        select(RestaurantSchedule)
        .where(RestaurantSchedule.restaurant_id == restaurant_id)
        .order_by(RestaurantSchedule.day_of_week, RestaurantSchedule.open_time)
    )
    return list(result.scalars().all())


async def get_timezone(db: AsyncSession) -> ZoneInfo:
    name = (await get_setting_value(db, "RESTAURANT_TIMEZONE", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning("Zona horaria inválida %r, usando %s", name, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)


def _today_hours(schedules: list[RestaurantSchedule], now: datetime) -> list[dict]:
    result = []
    for row in schedules:
        if row.day_of_week != now.weekday():
            continue
        result.append({
            "open": _format_time(row.open_time),
            "close": _format_time(row.close_time),
            "is_closed": bool(row.is_closed),
        })
    return result


async def restaurant_open_state(
    db: AsyncSession,
    restaurant: Restaurant,
    now: datetime | None = None,
    schedules: list[RestaurantSchedule] | None = None,
) -> dict:
    """Return the effective opening state of a restaurant.

    Keys: ``is_open_now``, ``message``, ``today_hours``, ``has_schedule``,
    ``next_open_at``.
    """
    if schedules is None:
        schedules = await get_schedules(db, restaurant.id)

    tz = await get_timezone(db)
    now = now.astimezone(tz) if now else datetime.now(tz)

    if not restaurant.is_open:
        return {
            "is_open_now": False,
            "message": "El restaurante no está recibiendo pedidos en este momento",
            "today_hours": _today_hours(schedules, now),
            "has_schedule": bool(schedules),
            "next_open_at": None,
        }

    if not schedules:
        return {
            "is_open_now": True,
            "message": "Abierto",
            "today_hours": [],
            "has_schedule": False,
            "next_open_at": None,
        }

    state = _evaluate(schedules, now)
    next_open_at = None
    if state["next_open"] is not None and state["next_open_offset"] is not None:
        date = now.date() + timedelta(days=state["next_open_offset"])
        next_open_at = datetime.combine(date, state["next_open"], tzinfo=tz)

    return {
        "is_open_now": bool(state["is_open"]),
        "message": state["message"],
        "today_hours": _today_hours(schedules, now),
        "has_schedule": True,
        "next_open_at": next_open_at.isoformat() if next_open_at else None,
    }


async def open_state_map(db: AsyncSession, restaurant_ids: list) -> dict:
    """Bulk evaluation used by restaurant listings (avoids N+1 queries)."""
    if not restaurant_ids:
        return {}
    result = await db.execute(
        select(RestaurantSchedule)
        .where(RestaurantSchedule.restaurant_id.in_(restaurant_ids))
        .order_by(RestaurantSchedule.day_of_week, RestaurantSchedule.open_time)
    )
    grouped: dict = {}
    for row in result.scalars().all():
        grouped.setdefault(row.restaurant_id, []).append(row)

    tz = await get_timezone(db)
    now = datetime.now(tz)
    states = {}
    for rid in restaurant_ids:
        schedules = grouped.get(rid, [])
        if not schedules:
            states[rid] = {
                "is_open_now": None,
                "message": "",
                "today_hours": [],
                "has_schedule": False,
                "next_open_at": None,
            }
            continue
        state = _evaluate(schedules, now)
        states[rid] = {
            "is_open_now": bool(state["is_open"]),
            "message": state["message"],
            "today_hours": _today_hours(schedules, now),
            "has_schedule": True,
            "next_open_at": None,
        }
    return states
