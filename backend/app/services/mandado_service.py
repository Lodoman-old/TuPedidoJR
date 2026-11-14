"""Fee calculation shared by mandado creation and estimates."""
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.order_service import get_setting_value
from app.services.route_service import route_distance_km


async def calculate_mandado_fees(
    db: AsyncSession,
    estimated_budget: Decimal,
    delivery_lat: float,
    delivery_lng: float,
    pickup_lat: float | None = None,
    pickup_lng: float | None = None,
) -> dict:
    """Return delivery, risk, platform and total for an open mandado.

    If pickup coordinates are known, the delivery fee uses the real
    pickup -> customer distance. Otherwise it uses the city center as a
    reference and the result is an estimate.
    """
    estimated_budget = Decimal(estimated_budget)

    city_lat = float(await get_setting_value(db, "CITY_CENTER_LAT", "20.644"))
    city_lng = float(await get_setting_value(db, "CITY_CENTER_LNG", "-100.993"))
    origin_lat = float(pickup_lat) if pickup_lat is not None else city_lat
    origin_lng = float(pickup_lng) if pickup_lng is not None else city_lng
    distance_km = None
    delivery_fee = Decimal("0.00")
    try:
        distance_km, _source = await route_distance_km(
            db, origin_lat, origin_lng, delivery_lat, delivery_lng,
        )
    except Exception:
        distance_km = None

    if distance_km is not None:
        base_fee = Decimal(await get_setting_value(db, "DELIVERY_BASE_FEE", "20.0"))
        free_radius = float(await get_setting_value(db, "DELIVERY_FREE_RADIUS_KM", "2.0"))
        extra_per_km = Decimal(await get_setting_value(db, "DELIVERY_EXTRA_FEE_PER_KM", "5.0"))
        if distance_km <= free_radius:
            delivery_fee = base_fee
        else:
            delivery_fee = base_fee + (Decimal(str(distance_km - free_radius)) * extra_per_km)

    risk_fee = Decimal(
        await get_setting_value(db, "MANDADO_RISK_FIXED_AMOUNT", "15.0")
    ).quantize(Decimal("0.01"))
    platform_fee = Decimal("0.00")
    estimated_total = estimated_budget + delivery_fee + risk_fee

    return {
        "estimated_budget": estimated_budget,
        "delivery_fee": delivery_fee,
        "distance_km": distance_km,
        "risk_type": "fixed",
        "risk_value": risk_fee,
        "risk_fee": risk_fee,
        "platform_fee": platform_fee,
        "estimated_total": estimated_total,
    }
