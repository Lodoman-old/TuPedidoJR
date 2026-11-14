"""Customer trust rules for high-value mandados."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mandado import Mandado
from app.models.order import Order
from app.models.user import User
from app.services.order_service import get_setting_value


async def _setting_int(db: AsyncSession, key: str, default: int) -> int:
    try:
        return int(float(await get_setting_value(db, key, str(default))))
    except (TypeError, ValueError):
        return default


async def _setting_money(db: AsyncSession, key: str, default: str) -> Decimal:
    try:
        return Decimal(await get_setting_value(db, key, default))
    except (TypeError, ValueError):
        return Decimal(default)


async def is_trusted_customer(db: AsyncSession, user: User) -> bool:
    if user.trusted_customer:
        return True
    min_days = await _setting_int(db, "MANDADO_TRUSTED_MIN_DAYS", 60)
    min_completed = await _setting_int(db, "MANDADO_TRUSTED_MIN_COMPLETED", 5)
    created_at = user.created_at
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at > datetime.now(timezone.utc) - timedelta(days=min_days):
        return False

    completed_orders = await db.scalar(
        select(func.count()).select_from(Order).where(
            Order.user_id == user.id,
            Order.status == "delivered",
        )
    )
    completed_mandados = await db.scalar(
        select(func.count()).select_from(Mandado).where(
            Mandado.user_id == user.id,
            Mandado.status == "completed",
        )
    )
    if int(completed_orders or 0) + int(completed_mandados or 0) < min_completed:
        return False

    since = datetime.now(timezone.utc) - timedelta(days=90)
    cancelled_orders = await db.scalar(
        select(func.count()).select_from(Order).where(
            Order.user_id == user.id,
            Order.status == "cancelled",
            Order.cancelled_at.is_not(None),
            Order.cancelled_at >= since,
        )
    )
    cancelled_mandados = await db.scalar(
        select(func.count()).select_from(Mandado).where(
            Mandado.user_id == user.id,
            Mandado.status == "cancelled",
            Mandado.created_at >= since,
        )
    )
    return int(cancelled_orders or 0) == 0 and int(cancelled_mandados or 0) == 0


async def mandado_payment_policy(
    db: AsyncSession, user: User, estimated_budget: Decimal
) -> dict:
    threshold = await _setting_money(db, "MANDADO_PREPAY_THRESHOLD", "1000.0")
    max_cash = await _setting_money(db, "MANDADO_TRUSTED_MAX_CASH", "3000.0")
    trusted = await is_trusted_customer(db, user)
    budget = Decimal(estimated_budget or 0)
    over_threshold = budget >= threshold
    over_trusted_cap = max_cash > 0 and budget > max_cash
    requires_prepayment = over_threshold and (not trusted or over_trusted_cap)
    return {
        "requires_prepayment": requires_prepayment,
        "trusted_customer": trusted,
        "threshold": threshold,
        "max_cash": max_cash,
    }
