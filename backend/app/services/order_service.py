import logging
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coupon import Coupon
from app.models.restaurant import Restaurant

logger = logging.getLogger(__name__)


async def get_setting_value(db: AsyncSession, key: str, default: str) -> str:
    from app.models.setting import Setting
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else default


async def get_approval_timeout_min(db: AsyncSession) -> int:
    raw = await get_setting_value(db, "DELIVERY_APPROVAL_TIMEOUT_MIN", "30")
    try:
        return max(int(float(raw)), 0)
    except (TypeError, ValueError):
        return 30


async def resolve_item_options(db: AsyncSession, menu_item, option_ids: list[str] | None):
    """Validate selected options and return (unit_price, selected_options)."""
    from decimal import Decimal
    from app.models.menu_option import MenuOptionGroup

    groups = list(menu_item.option_groups or [])
    selected = []
    by_group: dict = {}
    option_lookup = {
        str(option.id): (group, option)
        for group in groups
        for option in (group.options or [])
    }

    for option_id in option_ids or []:
        found = option_lookup.get(str(option_id))
        if not found:
            raise ValueError("Una opción seleccionada no pertenece a este platillo")
        group, option = found
        if not option.is_available:
            raise ValueError(f"La opción '{option.name}' no está disponible")
        by_group.setdefault(str(group.id), []).append(option)

    for group in groups:
        chosen = by_group.get(str(group.id), [])
        if group.is_required and len(chosen) < max(group.min_selections, 1):
            raise ValueError(f"Debes elegir una opción en '{group.name}'")
        if len(chosen) < group.min_selections:
            raise ValueError(
                f"Elige al menos {group.min_selections} opción(es) en '{group.name}'"
            )
        if len(chosen) > group.max_selections:
            raise ValueError(
                f"Elige máximo {group.max_selections} opción(es) en '{group.name}'"
            )
        if group.selection_type == "single" and len(chosen) > 1:
            raise ValueError(f"Solo puedes elegir una opción en '{group.name}'")

    unit_price = Decimal(menu_item.price or 0)
    selected = []
    for group in groups:
        chosen = by_group.get(str(group.id), [])
        if not chosen:
            continue
        is_max = group.pricing_mode == "max"
        portion = (Decimal("1") / Decimal(len(chosen))) if is_max else Decimal("1")
        if is_max:
            unit_price = max(
                unit_price,
                max(Decimal(option.price_delta or 0) for option in chosen),
            )
        else:
            unit_price += sum(
                (Decimal(option.price_delta or 0) for option in chosen),
                Decimal("0"),
            )
        for option in chosen:
            selected.append({
                "option_id": str(option.id),
                "group_name": group.name,
                "name": option.name,
                "price_delta": Decimal(option.price_delta or 0),
                "portion": portion,
            })
    return unit_price, selected






async def get_commission_rate(db: AsyncSession, restaurant: Restaurant) -> Decimal:
    """El porcentaje por platillo ya no se usa: el cobro es una cuota fija."""
    return Decimal("0")


def apply_commission(price: Decimal, rate: Decimal) -> Decimal:
    """Customer-facing price with the platform commission included."""
    base = Decimal(price or 0)
    if rate <= 0:
        return base.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (base * (Decimal("1") + rate / Decimal("100"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )


async def calculate_order_totals(
    db: AsyncSession,
    restaurant: Restaurant,
    items_data: list,
    coupon_code: str | None = None,
    delivery_lat: float = None,
    delivery_lng: float = None,
    tip_amount: Decimal = Decimal("0"),
    loyalty_discount: Decimal = Decimal("0"),
    pickup: bool = False,
) -> tuple:
    rate = Decimal("0")
    base_subtotal = Decimal("0.00")
    subtotal = Decimal("0.00")
    for entry in items_data:
        base_price = Decimal(entry["unit_price"] or 0)
        marked_price = base_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        entry["base_unit_price"] = base_price
        entry["unit_price"] = marked_price
        base_subtotal += base_price * entry["item"].quantity
        subtotal += marked_price * entry["item"].quantity

    base_fee = Decimal(await get_setting_value(db, "DELIVERY_BASE_FEE", "25.0"))
    delivery_fee = base_fee
    distance_km = None
    own_delivery = restaurant.delivery_mode == "own"
    if pickup:
        delivery_fee = Decimal("0")
    elif own_delivery:
        delivery_fee = Decimal(restaurant.delivery_fee or 0)
    elif delivery_lat is not None and delivery_lng is not None:
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
                distance_km, _source = await route_distance_km(
                    db,
                    float(row["lat"]),
                    float(row["lng"]),
                    delivery_lat,
                    delivery_lng,
                )
        except Exception as exc:
            logger.warning("No se pudo calcular la distancia, usando tarifa base: %s", exc)

        if distance_km is not None:
            free_radius_str = await get_setting_value(db, "DELIVERY_FREE_RADIUS_KM", "6.0")
            extra_per_km_str = await get_setting_value(db, "DELIVERY_EXTRA_FEE_PER_KM", "5.0")
            free_radius = float(free_radius_str)
            extra_per_km = Decimal(extra_per_km_str)
            if distance_km <= free_radius:
                delivery_fee = base_fee
            else:
                extra_km = Decimal(str(distance_km - free_radius))
                delivery_fee = base_fee + (extra_km * extra_per_km)

    fee_raw = restaurant.fixed_fee
    if fee_raw is None:
        fee_raw = await get_setting_value(db, "APP_FIXED_RESTAURANT_FEE", "5.0")
    try:
        platform_commission = Decimal(str(fee_raw or 0))
    except Exception:
        platform_commission = Decimal("0.00")
    platform_commission = max(
        Decimal("0.00"),
        min(platform_commission, subtotal),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    flat_fee_str = await get_setting_value(db, "APP_FLAT_USAGE_FEE", "5.0")
    flat_usage_fee = Decimal(flat_fee_str)

    discount = Decimal("0.00")
    coupon = None
    if coupon_code:
        result = await db.execute(select(Coupon).where(Coupon.code == coupon_code.upper()))
        coupon = result.scalar_one_or_none()
        if coupon and coupon.is_active:
            if coupon.discount_type == "percentage":
                raw = subtotal * (coupon.discount_value / Decimal("100"))
                if coupon.max_discount is not None and raw > coupon.max_discount:
                    raw = coupon.max_discount
                discount = raw
            else:
                discount = min(coupon.discount_value, subtotal)

    delivery_earnings = Decimal("0") if own_delivery or pickup else delivery_fee + Decimal(tip_amount or 0)
    total = (
        subtotal + delivery_fee + flat_usage_fee - discount - Decimal(loyalty_discount or 0)
        + Decimal(tip_amount or 0)
    )
    if total < 0:
        total = Decimal("0.00")

    return subtotal, delivery_fee, discount, total, coupon, platform_commission, flat_usage_fee, delivery_earnings, distance_km
