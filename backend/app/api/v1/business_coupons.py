"""Cupones administrados por cada negocio (descuento sobre su producto)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.coupon import Coupon
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.coupon import CouponCreate, CouponOut, CouponUpdate
from app.services.restaurant_access import MANAGE_ROLES, have_role

router = APIRouter()


async def _restaurant(db: AsyncSession, restaurant_id: str) -> Restaurant:
    restaurant = await db.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    return restaurant


async def _manage(db: AsyncSession, restaurant: Restaurant, user: User) -> None:
    if not await have_role(db, restaurant.id, user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No tienes acceso a este negocio")


def _check_values(
    discount_type: str,
    discount_value,
    max_discount,
    valid_from,
    valid_until,
) -> None:
    if discount_type == "percentage" and discount_value > 100:
        raise HTTPException(
            status_code=400, detail="El porcentaje no puede ser mayor a 100"
        )
    if max_discount is not None and max_discount < 0:
        raise HTTPException(status_code=400, detail="El tope no puede ser negativo")
    if valid_from and valid_until and valid_until <= valid_from:
        raise HTTPException(
            status_code=400, detail="La fecha final debe ser posterior a la inicial"
        )


@router.get("/{restaurant_id}/coupons", response_model=list[CouponOut])
async def list_coupons(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    result = await db.execute(
        select(Coupon)
        .where(Coupon.restaurant_id == restaurant.id)
        .order_by(Coupon.created_at.desc())
    )
    return [CouponOut.model_validate(row) for row in result.scalars().all()]


@router.post("/{restaurant_id}/coupons", response_model=CouponOut, status_code=201)
async def create_coupon(
    restaurant_id: str,
    body: CouponCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)

    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Escribe un código")
    _check_values(
        body.discount_type,
        body.discount_value,
        body.max_discount,
        body.valid_from,
        body.valid_until,
    )
    exists = await db.execute(select(Coupon.id).where(Coupon.code == code))
    if exists.scalar_one_or_none():
        raise HTTPException(
            status_code=409, detail="Ese código ya existe. Prueba con otro."
        )

    data = body.model_dump(exclude={"restaurant_id", "code"})
    coupon = Coupon(code=code, restaurant_id=restaurant.id, **data)
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return CouponOut.model_validate(coupon)


@router.patch("/{restaurant_id}/coupons/{coupon_id}", response_model=CouponOut)
async def update_coupon(
    restaurant_id: str,
    coupon_id: str,
    body: CouponUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    coupon = await db.get(Coupon, coupon_id)
    if not coupon or coupon.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Cupón no encontrado")

    data = body.model_dump(exclude_unset=True)
    if "code" in data:
        code = (data["code"] or "").strip().upper()
        if not code:
            raise HTTPException(status_code=400, detail="Escribe un código")
        exists = await db.execute(
            select(Coupon.id).where(Coupon.code == code, Coupon.id != coupon.id)
        )
        if exists.scalar_one_or_none():
            raise HTTPException(
                status_code=409, detail="Ese código ya existe. Prueba con otro."
            )
        data["code"] = code

    discount_type = data.get("discount_type", coupon.discount_type)
    discount_value = data.get("discount_value", coupon.discount_value)
    max_discount = data.get("max_discount", coupon.max_discount)
    valid_from = data.get("valid_from", coupon.valid_from)
    valid_until = data.get("valid_until", coupon.valid_until)
    _check_values(discount_type, discount_value, max_discount, valid_from, valid_until)

    for field, value in data.items():
        setattr(coupon, field, value)
    await db.commit()
    await db.refresh(coupon)
    return CouponOut.model_validate(coupon)


@router.delete("/{restaurant_id}/coupons/{coupon_id}", status_code=204)
async def deactivate_coupon(
    restaurant_id: str,
    coupon_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    coupon = await db.get(Coupon, coupon_id)
    if not coupon or coupon.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Cupón no encontrado")
    coupon.is_active = False
    await db.commit()
