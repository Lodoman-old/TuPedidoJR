import logging
import math

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant

logger = logging.getLogger(__name__)
AVG_DELIVERY_SPEED_KMH = 30


async def calculate_estimated_time(
    db: AsyncSession,
    restaurant: Restaurant,
    items_data: list,
    delivery_lng: float,
    delivery_lat: float,
    pickup: bool = False,
) -> int:
    base_prep = restaurant.preparation_base_time_min or 10
    max_item_prep = 0
    for entry in items_data:
        menu_item = entry.get("menu_item") if isinstance(entry, dict) else entry[0]
        prep = menu_item.preparation_time_min or 0
        if prep > max_item_prep:
            max_item_prep = prep

    prep_time = base_prep + max_item_prep

    if pickup:
        return prep_time

    try:
        result = await db.execute(
            text("""
                SELECT
                    ST_Y(r.location::geometry) AS lat,
                    ST_X(r.location::geometry) AS lng
                FROM restaurants r WHERE r.id = :rid
            """),
            {"rid": restaurant.id},
        )
        row = result.mappings().first()
        if row and row["lat"] is not None and row["lng"] is not None:
            from app.services.route_service import route_distance_km
            dist_km, _source = await route_distance_km(
                db,
                float(row["lat"]),
                float(row["lng"]),
                delivery_lat,
                delivery_lng,
            )
        else:
            dist_km = 1.0
    except Exception as exc:
        logger.warning("No se pudo calcular la distancia en estimación, usando 1 km: %s", exc)
        dist_km = 1.0

    travel_min = math.ceil((dist_km / AVG_DELIVERY_SPEED_KMH) * 60)
    total_min = prep_time + travel_min
    return total_min
