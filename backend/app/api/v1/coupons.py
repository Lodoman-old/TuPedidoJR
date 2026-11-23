from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.coupon import ValidateCouponRequest, ValidateCouponResponse
from app.services.coupon_service import evaluate_coupon

router = APIRouter()


@router.post("/validate", response_model=ValidateCouponResponse)
async def validate_coupon(
    body: ValidateCouponRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    coupon, discount, error = await evaluate_coupon(
        db, body.code, body.restaurant_id, body.subtotal
    )
    if error:
        return ValidateCouponResponse(valid=False, message=error)
    return ValidateCouponResponse(
        valid=True,
        message=f"Descuento aplicado: ${discount:.2f}",
        discount_amount=discount,
        discount_type=coupon.discount_type,
        discount_value=coupon.discount_value,
        coupon_id=str(coupon.id),
    )
