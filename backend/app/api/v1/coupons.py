from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.coupon import Coupon
from app.models.user import User
from app.schemas.coupon import ValidateCouponRequest, ValidateCouponResponse

router = APIRouter()


def _calc_discount(coupon: Coupon, subtotal: Decimal) -> tuple[Decimal, str]:
    if coupon.discount_type == "percentage":
        raw = subtotal * (coupon.discount_value / Decimal("100"))
        if coupon.max_discount is not None and raw > coupon.max_discount:
            raw = coupon.max_discount
        return raw, "percentage"
    else:
        return min(coupon.discount_value, subtotal), "fixed"


@router.post("/validate", response_model=ValidateCouponResponse)
async def validate_coupon(
    body: ValidateCouponRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Coupon).where(Coupon.code == body.code.upper()))
    coupon = result.scalar_one_or_none()

    if not coupon:
        return ValidateCouponResponse(valid=False, message="Cupón no encontrado")
    if not coupon.is_active:
        return ValidateCouponResponse(valid=False, message="Cupón inactivo")
    if coupon.max_uses > 0 and coupon.current_uses >= coupon.max_uses:
        return ValidateCouponResponse(valid=False, message="Cupón agotado")
    if coupon.valid_from and datetime.now(timezone.utc) < coupon.valid_from:
        return ValidateCouponResponse(valid=False, message="Cupón aún no válido")
    if coupon.valid_until and datetime.now(timezone.utc) > coupon.valid_until:
        return ValidateCouponResponse(valid=False, message="Cupón expirado")
    if body.subtotal < coupon.min_order_amount:
        return ValidateCouponResponse(
            valid=False,
            message=f"Pedido mínimo: ${coupon.min_order_amount:.2f}",
        )
    if coupon.restaurant_id and str(coupon.restaurant_id) != body.restaurant_id:
        return ValidateCouponResponse(valid=False, message="Cupón no válido para este restaurante")

    discount, dtype = _calc_discount(coupon, body.subtotal)
    return ValidateCouponResponse(
        valid=True,
        message=f"Descuento aplicado: ${discount:.2f}",
        discount_amount=discount,
        discount_type=dtype,
        discount_value=coupon.discount_value,
        coupon_id=str(coupon.id),
    )
