"""Loyalty points and referral bonuses."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.user import User
from app.services.order_service import get_setting_value


async def loyalty_config(db: AsyncSession) -> dict:
    enabled = (await get_setting_value(db, "LOYALTY_ENABLED", "true")).lower() == "true"
    visible = (await get_setting_value(db, "LOYALTY_VISIBLE", "true")).lower() == "true"
    try:
        points_per_100 = Decimal(await get_setting_value(db, "LOYALTY_POINTS_PER_100", "5"))
    except Exception:
        points_per_100 = Decimal("5")
    try:
        value_per_point = Decimal(await get_setting_value(db, "LOYALTY_VALUE_PER_POINT", "1.0"))
    except Exception:
        value_per_point = Decimal("1.0")
    try:
        referral_bonus = int(await get_setting_value(db, "REFERRAL_BONUS_POINTS", "50"))
    except Exception:
        referral_bonus = 50
    return {
        "enabled": enabled,
        "visible": visible,
        "points_per_100": max(points_per_100, Decimal("0")),
        "value_per_point": max(value_per_point, Decimal("0")),
        "referral_bonus": max(referral_bonus, 0),
    }


def earned_points(subtotal: Decimal, points_per_100: Decimal) -> int:
    if subtotal <= 0 or points_per_100 <= 0:
        return 0
    return int((Decimal(subtotal) / Decimal("100")) * points_per_100)


async def preview_redemption(
    db: AsyncSession,
    user: User,
    requested_points: int,
    subtotal: Decimal,
) -> tuple[int, Decimal]:
    config = await loyalty_config(db)
    if not config["enabled"] or requested_points <= 0:
        return 0, Decimal("0.00")
    value = config["value_per_point"]
    if value <= 0:
        return 0, Decimal("0.00")
    max_by_subtotal = int(Decimal(subtotal) / value)
    points = max(0, min(int(requested_points), int(user.loyalty_points or 0), max_by_subtotal))
    return points, (Decimal(points) * value).quantize(Decimal("0.01"))


async def apply_redemption(
    db: AsyncSession,
    user: User,
    requested_points: int,
    subtotal: Decimal,
) -> tuple[int, Decimal]:
    """Validate and reserve points for checkout. Returns (points, discount)."""
    config = await loyalty_config(db)
    if not config["enabled"] or requested_points <= 0:
        return 0, Decimal("0.00")
    value = config["value_per_point"]
    if value <= 0:
        return 0, Decimal("0.00")
    max_by_subtotal = int(Decimal(subtotal) / value)
    points = max(0, min(int(requested_points), int(user.loyalty_points or 0), max_by_subtotal))
    discount = (Decimal(points) * value).quantize(Decimal("0.01"))
    user.loyalty_points = int(user.loyalty_points or 0) - points
    return points, discount


async def award_on_delivery(db: AsyncSession, order: Order) -> None:
    config = await loyalty_config(db)
    if not config["enabled"] or order.points_awarded:
        return
    result = await db.execute(select(User).where(User.id == order.user_id))
    user = result.scalar_one_or_none()
    if not user:
        return

    points = earned_points(Decimal(order.subtotal or 0), config["points_per_100"])
    if points:
        user.loyalty_points = int(user.loyalty_points or 0) + points
    order.points_awarded = True

    if user.referred_by and not user.referral_bonus_awarded:
        bonus = config["referral_bonus"]
        if bonus:
            user.loyalty_points = int(user.loyalty_points or 0) + bonus
            referrer_result = await db.execute(
                select(User).where(User.id == user.referred_by)
            )
            referrer = referrer_result.scalar_one_or_none()
            if referrer:
                referrer.loyalty_points = int(referrer.loyalty_points or 0) + bonus
        user.referral_bonus_awarded = True
