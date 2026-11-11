from datetime import datetime
from math import asin, ceil, cos, radians, sin, sqrt

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order

AVG_DELIVERY_SPEED_KMH = 25
MIN_ETA_MIN = 1

# Status flow shown to the customer, in order.
TRACKING_STEPS: list[tuple[str, str]] = [
    ("pending", "Pedido recibido"),
    ("confirmed", "Confirmado por el restaurante"),
    ("preparing", "En preparación"),
    ("ready", "Listo para recoger"),
    ("in_delivery", "Repartidor en camino"),
    ("picked_up", "Pedido recogido"),
    ("delivered", "Entregado"),
]


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km. Free, no external routing service needed."""
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _step_timestamps(order: Order) -> dict[str, datetime | None]:
    return {
        "pending": order.placed_at,
        "confirmed": order.confirmed_at,
        "preparing": None,
        "ready": None,
        "in_delivery": None,
        "picked_up": order.picked_up_at,
        "delivered": order.delivered_at,
    }


async def build_tracking(db: AsyncSession, order: Order) -> dict:
    """Build the customer-facing tracking payload using only local data/PostGIS.

    No paid maps, routing or geocoding providers are involved.
    """
    rows = await db.execute(
        text("""
            SELECT
                ST_Y(o.delivery_location::geometry) AS dest_lat,
                ST_X(o.delivery_location::geometry) AS dest_lng,
                ST_Y(r.location::geometry) AS resto_lat,
                ST_X(r.location::geometry) AS resto_lng,
                ST_Y(dp.current_location::geometry) AS courier_lat,
                ST_X(dp.current_location::geometry) AS courier_lng
            FROM orders o
            LEFT JOIN restaurants r ON r.id = o.restaurant_id
            LEFT JOIN delivery_persons dp ON dp.id = o.delivery_person_id
            WHERE o.id = :oid
        """),
        {"oid": order.id},
    )
    row = rows.mappings().first()

    restaurant = None
    destination = None
    courier = None
    if row:
        if row["resto_lat"] is not None and row["resto_lng"] is not None:
            restaurant = {"lat": float(row["resto_lat"]), "lng": float(row["resto_lng"])}
        if row["dest_lat"] is not None and row["dest_lng"] is not None:
            destination = {"lat": float(row["dest_lat"]), "lng": float(row["dest_lng"])}
        if row["courier_lat"] is not None and row["courier_lng"] is not None:
            courier = {"lat": float(row["courier_lat"]), "lng": float(row["courier_lng"])}

    courier_updated_at = None
    if courier is None:
        # Fall back to the last persisted location for this order.
        latest = await db.execute(
            text("""
                SELECT
                    ST_Y(location::geometry) AS lat,
                    ST_X(location::geometry) AS lng,
                    recorded_at
                FROM delivery_locations
                WHERE order_id = :oid
                ORDER BY recorded_at DESC
                LIMIT 1
            """),
            {"oid": order.id},
        )
        loc = latest.mappings().first()
        if loc and loc["lat"] is not None:
            courier = {"lat": float(loc["lat"]), "lng": float(loc["lng"])}
            courier_updated_at = loc["recorded_at"]

    steps = _step_timestamps(order)
    tracking_steps = TRACKING_STEPS
    pickup = order.delivery_mode == "pickup" or getattr(order, "fulfillment_type", "delivery") == "pickup"
    if pickup:
        tracking_steps = [
            ("pending", "Pedido recibido"),
            ("confirmed", "Confirmado por el restaurante"),
            ("preparing", "En preparación"),
            ("ready", "Listo para recoger"),
            ("delivered", "Recogido"),
        ]
    elif order.delivery_mode == "own":
        tracking_steps = [
            ("pending", "Pedido recibido"),
            ("confirmed", "Confirmado por el restaurante"),
            ("preparing", "En preparación"),
            ("ready", "Listo"),
            ("in_delivery", "En reparto por el restaurante"),
            ("delivered", "Entregado"),
        ]
    keys = [key for key, _ in tracking_steps]
    current_index = keys.index(order.status) if order.status in keys else -1

    timeline = [
        {
            "key": key,
            "label": label,
            "completed": order.status != "cancelled" and current_index >= idx,
            "at": steps.get(key),
        }
        for idx, (key, label) in enumerate(tracking_steps)
    ]

    # Remaining distance: courier -> customer, or restaurant -> customer if the
    # courier has not reported a location yet.
    reference = None if pickup else (courier or restaurant)
    distance_km = None
    eta_min = None
    if not pickup and order.status not in ("delivered", "cancelled") and reference and destination:
        distance_km = _haversine_km(reference["lat"], reference["lng"], destination["lat"], destination["lng"])
        eta_min = max(MIN_ETA_MIN, ceil(distance_km / AVG_DELIVERY_SPEED_KMH * 60))

    return {
        "order_id": order.id,
        "status": order.status,
        "timeline": timeline,
        "restaurant": restaurant,
        "destination": destination,
        "courier": courier,
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "eta_min": eta_min,
        "estimated_delivery_min": order.estimated_delivery_min,
        "courier_updated_at": courier_updated_at,
    }


MANDADO_STEPS: list[tuple[str, str]] = [
    ("pending", "Solicitud recibida"),
    ("accepted", "Repartidor asignado"),
    ("purchased", "Compra realizada"),
    ("completed", "Entregado"),
]

MANDADO_STEP_TIMESTAMPS = {
    "pending": "created_at",
    "accepted": "accepted_at",
    "purchased": "purchased_at",
    "completed": "delivered_at",
}


async def build_mandado_tracking(db: AsyncSession, mandado) -> dict:
    """Customer-facing tracking for a mandado (no external services)."""
    rows = await db.execute(
        text("""
            SELECT
                ST_Y(m.delivery_location::geometry) AS dest_lat,
                ST_X(m.delivery_location::geometry) AS dest_lng,
                ST_Y(dp.current_location::geometry) AS courier_lat,
                ST_X(dp.current_location::geometry) AS courier_lng
            FROM mandados m
            LEFT JOIN delivery_persons dp ON dp.id = m.delivery_person_id
            WHERE m.id = :mid
        """),
        {"mid": mandado.id},
    )
    row = rows.mappings().first()

    destination = None
    courier = None
    if row:
        if row["dest_lat"] is not None and row["dest_lng"] is not None:
            destination = {"lat": float(row["dest_lat"]), "lng": float(row["dest_lng"])}
        if row["courier_lat"] is not None and row["courier_lng"] is not None:
            courier = {"lat": float(row["courier_lat"]), "lng": float(row["courier_lng"])}

    keys = [key for key, _ in MANDADO_STEPS]
    current_index = keys.index(mandado.status) if mandado.status in keys else -1

    timeline = []
    for idx, (key, label) in enumerate(MANDADO_STEPS):
        at = getattr(mandado, MANDADO_STEP_TIMESTAMPS[key], None)
        timeline.append({
            "key": key,
            "label": label,
            "completed": mandado.status != "cancelled" and current_index >= idx,
            "at": at,
        })

    distance_km = None
    eta_min = None
    if (
        mandado.status not in ("completed", "cancelled")
        and courier
        and destination
    ):
        distance_km = _haversine_km(
            courier["lat"], courier["lng"], destination["lat"], destination["lng"]
        )
        eta_min = max(MIN_ETA_MIN, ceil(distance_km / AVG_DELIVERY_SPEED_KMH * 60))

    return {
        "mandado_id": mandado.id,
        "status": mandado.status,
        "timeline": timeline,
        "destination": destination,
        "courier": courier,
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "eta_min": eta_min,
        "estimated_total": mandado.estimated_total,
        "final_total": mandado.final_total,
        "payment_method": mandado.payment_method,
    }
