"""Cálculo de tarifas y seguimiento de envíos de negocio."""
import secrets
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.restaurant import Restaurant
from app.models.shipment import Shipment
from app.schemas.order import TrackPoint
from app.schemas.shipment import ShipmentTrackingOut, ShipmentTrackingStep
from app.services.order_service import get_setting_value
from app.services.route_service import route_distance_km, route_info


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def new_pickup_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(6))


def new_delivery_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(4))


async def store_coords(db: AsyncSession, store_id) -> tuple[float | None, float | None]:
    result = await db.execute(
        text(
            "SELECT ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng "
            "FROM restaurants WHERE id = :id"
        ),
        {"id": store_id},
    )
    row = result.mappings().first()
    if row and row["lat"] is not None and row["lng"] is not None:
        return float(row["lat"]), float(row["lng"])
    return None, None


async def calculate_shipment_fees(
    db: AsyncSession,
    store_id,
    delivery_lat: float,
    delivery_lng: float,
    collect_amount=0,
    shipping_paid_by: str = "store",
) -> dict:
    base_fee = money(await get_setting_value(db, "DELIVERY_BASE_FEE", "25.0"))
    free_radius = float(await get_setting_value(db, "DELIVERY_FREE_RADIUS_KM", "6"))
    extra_per_km = money(await get_setting_value(db, "DELIVERY_EXTRA_FEE_PER_KM", "5.0"))
    platform_fee = money(await get_setting_value(db, "SHIPMENT_PLATFORM_FEE", "10.0"))

    distance_km = None
    store_lat, store_lng = await store_coords(db, store_id)
    if store_lat is not None and store_lng is not None:
        try:
            distance_km, _source = await route_distance_km(
                db, store_lat, store_lng, delivery_lat, delivery_lng
            )
        except Exception:
            distance_km = None

    if distance_km is None or distance_km <= free_radius:
        delivery_fee = base_fee
    else:
        delivery_fee = money(
            base_fee + (Decimal(str(distance_km - free_radius)) * extra_per_km)
        )

    collect = money(collect_amount)
    amount_to_collect = money(
        collect + (delivery_fee if shipping_paid_by == "recipient" else 0)
    )
    store_charge = money(
        platform_fee + (delivery_fee if shipping_paid_by == "store" else 0)
    )

    return {
        "delivery_fee": delivery_fee,
        "platform_fee": platform_fee,
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "amount_to_collect": amount_to_collect,
        "store_charge": store_charge,
    }


async def build_shipment_tracking(
    db: AsyncSession, shipment: Shipment
) -> ShipmentTrackingOut:
    store = await db.get(Restaurant, shipment.store_id)
    destination = None
    coords = await db.execute(
        text(
            "SELECT ST_Y(delivery_location::geometry) AS lat, "
            "ST_X(delivery_location::geometry) AS lng "
            "FROM shipments WHERE id = :id"
        ),
        {"id": shipment.id},
    )
    row = coords.mappings().first()
    if row and row["lat"] is not None and row["lng"] is not None:
        destination = TrackPoint(lat=float(row["lat"]), lng=float(row["lng"]))

    courier = None
    if shipment.delivery_person_id:
        courier_row = await db.execute(
            text(
                "SELECT ST_Y(current_location::geometry) AS lat, "
                "ST_X(current_location::geometry) AS lng "
                "FROM delivery_persons WHERE id = :id"
            ),
            {"id": shipment.delivery_person_id},
        )
        point = courier_row.mappings().first()
        if point and point["lat"] is not None and point["lng"] is not None:
            courier = TrackPoint(lat=float(point["lat"]), lng=float(point["lng"]))

    distance_km = None
    eta_min = None
    if courier and destination:
        try:
            distance, duration, _source = await route_info(
                db, courier.lat, courier.lng, destination.lat, destination.lng
            )
            distance_km = round(distance, 2)
            eta_min = max(1, int(round(duration)))
        except Exception:
            distance_km = None
            eta_min = None

    steps = [
        ShipmentTrackingStep(
            key="created", label="Envío creado", completed=True,
            at=shipment.created_at,
        ),
        ShipmentTrackingStep(
            key="accepted", label="Repartidor asignado",
            completed=bool(shipment.accepted_at), at=shipment.accepted_at,
        ),
        ShipmentTrackingStep(
            key="picked_up", label="Paquete recogido",
            completed=bool(shipment.picked_up_at), at=shipment.picked_up_at,
        ),
    ]
    if shipment.status == "cancelled":
        steps.append(
            ShipmentTrackingStep(
                key="cancelled", label="Envío cancelado", completed=True,
                at=shipment.cancelled_at,
            )
        )
    elif shipment.status == "failed":
        steps.append(
            ShipmentTrackingStep(
                key="failed", label="No se pudo entregar", completed=True,
                at=shipment.updated_at,
            )
        )
    else:
        steps.append(
            ShipmentTrackingStep(
                key="delivered", label="Entregado",
                completed=bool(shipment.delivered_at), at=shipment.delivered_at,
            )
        )

    return ShipmentTrackingOut(
        shipment_id=shipment.id,
        status=shipment.status,
        store_name=store.name if store else "",
        store_logo_url=store.logo_url if store else None,
        recipient_name=shipment.recipient_name,
        delivery_address=shipment.delivery_address,
        package_description=shipment.package_description,
        amount_to_collect=shipment.amount_to_collect,
        timeline=steps,
        destination=destination,
        courier=courier,
        distance_km=distance_km,
        eta_min=eta_min,
        delivery_code=(
            shipment.delivery_code if shipment.status == "picked_up" else None
        ),
    )
