"""Cupones administrados por cada negocio (descuento sobre su producto)."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.coupon import Coupon
from app.models.coupon_campaign import CouponCampaign
from app.models.order import Order
from app.models.push_token import PushToken
from app.models.restaurant import Restaurant
from app.models.restaurant_user import RestaurantUser
from app.models.user import User
from app.schemas.coupon import CouponCreate, CouponOut, CouponUpdate
from app.services.audit_service import log_action
from app.services.email_service import send_coupon_campaign
from app.services.order_service import get_setting_value
from app.services.push_service import send_to_tokens
from app.services.restaurant_access import MANAGE_ROLES, have_role

logger = logging.getLogger(__name__)
router = APIRouter()


class CouponCampaignRequest(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["push"], min_length=1)


async def _restaurant(db: AsyncSession, restaurant_id: str) -> Restaurant:
    restaurant = await db.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    return restaurant


async def _manage(db: AsyncSession, restaurant: Restaurant, user: User) -> None:
    if not await have_role(db, restaurant.id, user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No tienes acceso a este negocio")


async def _coupon(
    db: AsyncSession, restaurant: Restaurant, coupon_id: str
) -> Coupon:
    coupon = await db.get(Coupon, coupon_id)
    if not coupon or coupon.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Cupón no encontrado")
    return coupon


async def _audience(
    db: AsyncSession, restaurant: Restaurant
) -> tuple[list, list[str]]:
    """Clientes que ya pidieron y recibieron en este negocio."""
    staff = select(RestaurantUser.user_id).where(
        RestaurantUser.restaurant_id == restaurant.id
    )
    rows = (
        await db.execute(
            select(User.id, User.email)
            .join(Order, Order.user_id == User.id)
            .where(
                Order.restaurant_id == restaurant.id,
                Order.status == "delivered",
                User.is_active.is_(True),
                User.is_superuser.is_(False),
                User.id != restaurant.owner_id,
                User.id.not_in(staff),
            )
            .distinct()
        )
    ).all()
    user_ids = [row.id for row in rows]
    emails = sorted(
        {(row.email or "").strip().lower() for row in rows if row.email}
    )
    return user_ids, emails


async def _push_count(db: AsyncSession, user_ids: list) -> int:
    if not user_ids:
        return 0
    total = await db.scalar(
        select(func.count())
        .select_from(PushToken)
        .where(
            PushToken.user_id.in_(user_ids),
            PushToken.is_active.is_(True),
        )
    )
    return int(total or 0)


async def _last_campaign(db: AsyncSession, coupon_id) -> CouponCampaign | None:
    return await db.scalar(
        select(CouponCampaign)
        .where(CouponCampaign.coupon_id == coupon_id)
        .order_by(CouponCampaign.created_at.desc())
        .limit(1)
    )


def _campaign_dict(campaign: CouponCampaign | None) -> dict | None:
    if not campaign:
        return None
    return {
        "id": str(campaign.id),
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "channels": campaign.channels,
        "audience": campaign.audience_count,
        "push_sent": campaign.push_sent,
        "push_failed": campaign.push_failed,
        "email_sent": campaign.email_sent,
        "email_failed": campaign.email_failed,
    }


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
            status_code=400,
            detail="La fecha final debe ser posterior a la inicial",
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
    coupon = await _coupon(db, restaurant, coupon_id)

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
    coupon = await _coupon(db, restaurant, coupon_id)
    coupon.is_active = False
    await db.commit()


@router.get("/{restaurant_id}/coupons/{coupon_id}/audience")
async def coupon_audience(
    restaurant_id: str,
    coupon_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    coupon = await _coupon(db, restaurant, coupon_id)

    user_ids, emails = await _audience(db, restaurant)
    push_count = await _push_count(db, user_ids)
    last = await _last_campaign(db, coupon.id)
    now = datetime.now(timezone.utc)
    can_send = not (last and last.created_at >= now - timedelta(days=1))
    next_send_at = None
    if not can_send and last:
        next_send_at = (last.created_at + timedelta(days=1)).isoformat()

    return {
        "coupon_id": str(coupon.id),
        "code": coupon.code,
        "customers": len(user_ids),
        "push_devices": push_count,
        "emails": len(emails),
        "can_send": can_send,
        "next_send_at": next_send_at,
        "last_campaign": _campaign_dict(last),
    }


@router.post("/{restaurant_id}/coupons/{coupon_id}/campaign")
async def send_coupon_campaign_action(
    restaurant_id: str,
    coupon_id: str,
    body: CouponCampaignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    coupon = await _coupon(db, restaurant, coupon_id)

    now = datetime.now(timezone.utc)
    if not coupon.is_active:
        raise HTTPException(status_code=400, detail="El cupón está pausado.")
    if coupon.valid_until and coupon.valid_until < now:
        raise HTTPException(status_code=400, detail="El cupón ya venció.")
    if coupon.max_uses > 0 and coupon.current_uses >= coupon.max_uses:
        raise HTTPException(
            status_code=400, detail="El cupón ya alcanzó sus usos máximos."
        )

    last = await _last_campaign(db, coupon.id)
    if last and last.created_at >= now - timedelta(days=1):
        raise HTTPException(
            status_code=429,
            detail=(
                "Ya enviaste una campaña con este cupón en las últimas 24 horas."
            ),
        )

    channels = sorted(
        {channel for channel in body.channels if channel in {"push", "email"}}
    )
    if not channels:
        raise HTTPException(
            status_code=400, detail="Elige push, correo o ambos."
        )

    user_ids, emails = await _audience(db, restaurant)
    if not user_ids:
        raise HTTPException(
            status_code=400,
            detail="Todavía no tienes clientes con pedidos entregados.",
        )
    push_count = await _push_count(db, user_ids)
    if "push" in channels and push_count == 0:
        channels.remove("push")
    if "email" in channels and not emails:
        channels.remove("email")
    if not channels:
        raise HTTPException(
            status_code=400,
            detail="No hay dispositivos push ni correos disponibles.",
        )

    base = (
        await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)
    ).rstrip("/")
    path = (
        f"/r/{restaurant.slug}"
        if restaurant.slug
        else f"/web/restaurants/{restaurant.id}"
    )
    link = f"{base}{path}?coupon={coupon.code}"

    if coupon.discount_type == "percentage":
        discount_label = f"{float(coupon.discount_value):g}% de descuento"
    else:
        discount_label = f"${float(coupon.discount_value):,.2f} de descuento"
    min_order_label = (
        f"En compras desde ${float(coupon.min_order_amount):,.2f}."
        if coupon.min_order_amount and float(coupon.min_order_amount) > 0
        else ""
    )
    valid_until_label = (
        f"Válido hasta {coupon.valid_until.strftime('%d/%m/%Y')}."
        if coupon.valid_until
        else ""
    )

    push_stats = {"sent": 0, "failed": 0, "deactivated": 0}
    email_sent = 0
    email_failed = 0

    if "push" in channels:
        tokens = (
            await db.execute(
                select(PushToken).where(
                    PushToken.user_id.in_(user_ids),
                    PushToken.is_active.is_(True),
                )
            )
        ).scalars().all()
        title = f"{restaurant.name}: {coupon.description or 'Cupón exclusivo'}"
        push_body = f"Usa el código {coupon.code} y obtén {discount_label}."
        push_stats = await send_to_tokens(
            db,
            tokens,
            title,
            push_body,
            {
                "type": "coupon",
                "code": coupon.code,
                "restaurant_id": str(restaurant.id),
                "url": link,
            },
            style="amber",
        )

    if "email" in channels:
        for email in emails:
            try:
                ok, _detail = await send_coupon_campaign(
                    db,
                    email,
                    restaurant.name,
                    coupon.code,
                    coupon.description,
                    discount_label,
                    min_order_label,
                    valid_until_label,
                    link,
                )
            except Exception:
                logger.exception(
                    "No se pudo enviar campaña de cupón a %s", email
                )
                ok = False
            if ok:
                email_sent += 1
            else:
                email_failed += 1

    campaign = CouponCampaign(
        coupon_id=coupon.id,
        restaurant_id=restaurant.id,
        created_by=current_user.id,
        channels=",".join(channels),
        audience_count=len(user_ids),
        push_sent=push_stats["sent"],
        push_failed=push_stats["failed"],
        email_sent=email_sent,
        email_failed=email_failed,
    )
    db.add(campaign)
    await log_action(
        db,
        current_user.id,
        "coupon.campaign",
        "coupon",
        coupon.id,
        {
            "channels": channels,
            "audience": len(user_ids),
            "push_sent": push_stats["sent"],
            "email_sent": email_sent,
        },
    )
    await db.commit()
    await db.refresh(campaign)
    return {
        "campaign_id": str(campaign.id),
        "channels": channels,
        "audience": len(user_ids),
        "push_sent": push_stats["sent"],
        "push_failed": push_stats["failed"],
        "email_sent": email_sent,
        "email_failed": email_failed,
        "message": "Campaña enviada.",
    }
