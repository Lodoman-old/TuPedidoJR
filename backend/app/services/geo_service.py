from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.delivery import DeliveryPersonAvailable
from app.schemas.restaurant import RestaurantListItem


async def find_nearby_delivery_persons(
    db: AsyncSession,
    lat: float,
    lng: float,
    radius_m: int = 3000,
) -> list[DeliveryPersonAvailable]:
    sql = text("""
        SELECT dp.id, u.name, dp.vehicle_type, dp.rating,
               ST_Distance(dp.current_location::geography,
                           ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) AS distance_m
        FROM delivery_persons dp
        JOIN users u ON u.id = dp.user_id
        WHERE dp.is_available = true
          AND dp.current_location IS NOT NULL
          AND ST_DWithin(
                dp.current_location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius
              )
        ORDER BY distance_m
        LIMIT 20
    """)
    result = await db.execute(sql, {"lat": lat, "lng": lng, "radius": radius_m})
    rows = result.fetchall()
    return [
        DeliveryPersonAvailable(
            id=str(row.id),
            name=row.name,
            vehicle_type=row.vehicle_type,
            distance_m=float(row.distance_m),
            rating=float(row.rating),
        )
        for row in rows
    ]


async def get_nearby_restaurants(
    db: AsyncSession,
    lat: float,
    lng: float,
    q: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> list[RestaurantListItem]:
    where_clause = ""
    if q:
        where_clause = """
            AND (
                r.name ILIKE :q
                OR r.cuisine ILIKE :q
                OR r.description ILIKE :q
                OR EXISTS (
                    SELECT 1 FROM menu_items mi
                    WHERE mi.restaurant_id = r.id AND mi.name ILIKE :q
                )
                OR EXISTS (
                    SELECT 1 FROM menu_categories mc
                    WHERE mc.restaurant_id = r.id AND mc.name ILIKE :q
                )
            )
        """

    sql = text(f"""
        SELECT r.id, r.name, r.description, r.cuisine, r.slug, r.delivery_mode, r.logo_url, r.is_open, r.rating,
               r.delivery_fee,
               ST_Distance(r.location::geography,
                           ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) AS distance_m
        FROM restaurants r
        WHERE r.status = 'active'
              {where_clause}
        ORDER BY distance_m
        LIMIT :limit OFFSET :skip
    """)
    params = {"lat": lat, "lng": lng, "limit": limit, "skip": skip}
    if q:
        params["q"] = f"%{q}%"

    result = await db.execute(sql, params)
    rows = result.fetchall()
    return [
        RestaurantListItem(
            id=str(row.id),
            name=row.name,
            description=row.description,
            cuisine=row.cuisine,
            slug=row.slug,
            delivery_mode=row.delivery_mode,
            logo_url=row.logo_url,
            is_open=row.is_open,
            rating=float(row.rating),
            delivery_fee=float(row.delivery_fee),
            distance_m=float(row.distance_m),
        )
        for row in rows
    ]
