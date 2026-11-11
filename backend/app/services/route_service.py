import logging
import math

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.setting_service import get_setting

logger = logging.getLogger(__name__)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


async def route_info(
    db: AsyncSession,
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
    average_speed_kmh: float = 25.0,
) -> tuple[float, float, str]:
    """Return (distance_km, duration_min, source) between two points.

    If ``OSRM_URL`` is configured (self-hosted OSRM), returns the real driving
    route distance and duration. Otherwise falls back to straight-line distance
    multiplied by ``ROUTE_DISTANCE_FACTOR`` and an average speed.
    """
    osrm_url = (await get_setting(db, "OSRM_URL", "") or "").strip()
    if osrm_url:
        try:
            url = (
                f"{osrm_url.rstrip('/')}/route/v1/driving/"
                f"{lng1},{lat1};{lng2},{lat2}"
            )
            async with httpx.AsyncClient(timeout=4) as client:
                response = await client.get(
                    url,
                    params={"overview": "false", "alternatives": "false"},
                )
            if response.status_code == 200:
                data = response.json()
                routes = data.get("routes") or []
                if routes:
                    distance = float(routes[0]["distance"]) / 1000.0
                    duration = float(routes[0]["duration"]) / 60.0
                    return distance, duration, "osrm"
            logger.warning("OSRM no devolvió ruta: %s", response.text[:200])
        except Exception as exc:
            logger.warning("OSRM no disponible, usando distancia lineal: %s", exc)

    distance = haversine_km(lat1, lng1, lat2, lng2)
    try:
        factor = float(await get_setting(db, "ROUTE_DISTANCE_FACTOR", "1.0") or "1.0")
    except (TypeError, ValueError):
        factor = 1.0
    distance = distance * max(factor, 0.1)
    duration = (distance / max(average_speed_kmh, 5.0)) * 60.0
    return distance, duration, "lineal"


async def route_distance_km(
    db: AsyncSession,
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
) -> tuple[float, str]:
    distance, _duration, source = await route_info(db, lat1, lng1, lat2, lng2)
    return distance, source
