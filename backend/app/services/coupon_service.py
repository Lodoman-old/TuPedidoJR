"""Reglas de cupones compartidas por validación y creación de pedidos."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coupon import Coupon
from app.services.rounding import round_half_down


async def evaluate_coupon(
    db: AsyncSession,
    code: str | None,
    restaurant_id,
    subtotal: Decimal,
) -> tuple[Coupon | None, Decimal, str | None]:
    """Devuelve (cupón, descuento, error). El error es None si es válido."""
    value = (code or "").strip().upper()
    if not value:
        return None, Decimal("0.00"), "Escribe un código de cupón"

    coupon = (
        await db.execute(select(Coupon).where(Coupon.code == value))
    ).scalar_one_or_none()
    if not coupon:
        return None, Decimal("0.00"), "Cupón no encontrado"
    if not coupon.is_active:
        return None, Decimal("0.00"), "Cupón inactivo"

    now = datetime.now(timezone.utc)
    if coupon.valid_from and now < coupon.valid_from:
        return None, Decimal("0.00"), "Cupón aún no válido"
    if coupon.valid_until and now > coupon.valid_until:
        return None, Decimal("0.00"), "Cupón expirado"
    if coupon.max_uses > 0 and coupon.current_uses >= coupon.max_uses:
        return None, Decimal("0.00"), "Cupón agotado"
    if coupon.restaurant_id and str(coupon.restaurant_id) != str(restaurant_id):
        return None, Decimal("0.00"), "Cupón no válido para este negocio"
    if subtotal < coupon.min_order_amount:
        return (
            None,
            Decimal("0.00"),
            f"Pedido mínimo: ${coupon.min_order_amount:.2f}",
        )

    if coupon.discount_type == "percentage":
        raw = subtotal * (coupon.discount_value / Decimal("100"))
        if coupon.max_discount is not None and raw > coupon.max_discount:
            raw = coupon.max_discount
    else:
        raw = coupon.discount_value

    discount = round_half_down(min(raw, subtotal))
    if discount <= 0:
        return None, Decimal("0.00"), "El cupón no aplica a este pedido"
    return coupon, discount, None
