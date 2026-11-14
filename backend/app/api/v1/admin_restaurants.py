"""Admin approval for restaurant self-registrations."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.restaurant import Restaurant
from app.models.restaurant_user import RestaurantUser
from app.models.user import User
from app.schemas.restaurant import RestaurantApprovalRequest, RestaurantRegistrationOut
from app.services.audit_service import log_action
from app.services.email_service import send_email, send_restaurant_rejected, send_restaurant_welcome

router = APIRouter()


@router.post("/email/test")
async def send_test_email(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    to = (body.get("to") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Escribe un correo de destino")
    sent, detail = await send_email(
        db, to, "Correo de prueba — TuPedidoJR",
        "<p>La configuración SMTP de TuPedidoJR funciona correctamente.</p>",
        "La configuración SMTP de TuPedidoJR funciona correctamente.",
    )
    if not sent:
        raise HTTPException(status_code=400, detail=detail)
    return {"message": "Correo de prueba enviado"}


def _row(restaurant: Restaurant, owner: User | None) -> RestaurantRegistrationOut:
    return RestaurantRegistrationOut(
        id=restaurant.id,
        name=restaurant.name,
        cuisine=restaurant.cuisine,
        business_type=restaurant.business_type or "restaurant",
        address=restaurant.address,
        phone=restaurant.phone,
        status=restaurant.status,
        owner_name=owner.name if owner else "—",
        owner_email=owner.email if owner else "—",
        created_at=restaurant.created_at,
        rejection_reason=restaurant.rejection_reason,
    )


@router.get("/restaurant-registrations", response_model=list[RestaurantRegistrationOut])
async def list_restaurant_registrations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(Restaurant, User)
        .outerjoin(User, User.id == Restaurant.owner_id)
        .order_by(Restaurant.created_at.desc())
    )
    return [_row(restaurant, owner) for restaurant, owner in result.all()]


@router.get("/restaurant-registrations/pending-count")
async def pending_restaurant_registrations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    total = await db.scalar(
        select(func.count()).select_from(Restaurant).where(Restaurant.status == "pending")
    )
    return {"pending": int(total or 0)}


class AffiliationUpdate(BaseModel):
    paid: bool | None = None
    expires_at: date | None = None


class BusinessTypeUpdate(BaseModel):
    business_type: str = Field(
        ...,
        pattern="^(restaurant|store|pharmacy|grocery|hardware|other)$",
    )


def _affiliation_row(restaurant: Restaurant) -> dict:
    today = date.today()
    expires = restaurant.affiliation_expires_at
    days_left = (expires - today).days if expires else None
    return {
        "id": str(restaurant.id),
        "name": restaurant.name,
        "cuisine": restaurant.cuisine,
        "status": restaurant.status,
        "affiliation_expires_at": expires.isoformat() if expires else None,
        "days_left": days_left,
        "affiliated": bool(expires and expires >= today),
    }


@router.patch("/restaurants/{restaurant_id}/business-type")
async def update_business_type(
    restaurant_id: str,
    body: BusinessTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    try:
        rid = uuid.UUID(restaurant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Negocio inválido") from exc
    result = await db.execute(select(Restaurant).where(Restaurant.id == rid))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    previous = restaurant.business_type
    restaurant.business_type = body.business_type
    await log_action(
        db, current_user.id, "restaurant.business_type.update", "restaurant",
        restaurant.id, {"from": previous, "to": body.business_type},
    )
    await db.commit()
    await db.refresh(restaurant)
    owner = await db.get(User, restaurant.owner_id)
    return _row(restaurant, owner)


@router.get("/affiliations")
async def list_affiliations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(Restaurant)
        .where(Restaurant.status == "active")
        .order_by(Restaurant.name)
    )
    return [_affiliation_row(row) for row in result.scalars().all()]


@router.patch("/affiliations/{restaurant_id}")
async def update_affiliation(
    restaurant_id: str,
    body: AffiliationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")

    if body.paid is True:
        base = date.today()
        current = restaurant.affiliation_expires_at
        if current and current >= base:
            base = current
        restaurant.affiliation_expires_at = base + timedelta(days=365)
    elif body.paid is False:
        restaurant.affiliation_expires_at = None
    elif body.expires_at is not None:
        restaurant.affiliation_expires_at = body.expires_at
    else:
        raise HTTPException(status_code=400, detail="Indica si pagó o la fecha de vencimiento")

    restaurant.affiliation_reminder_on = None
    await log_action(
        db, current_user.id, "affiliation.update", "restaurant", restaurant.id,
        {"expires_at": restaurant.affiliation_expires_at.isoformat() if restaurant.affiliation_expires_at else None},
    )
    await db.commit()
    await db.refresh(restaurant)
    return _affiliation_row(restaurant)


@router.post("/restaurant-registrations/{restaurant_id}/approve")
async def approve_restaurant(
    restaurant_id: str,
    body: RestaurantApprovalRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    try:
        rid = uuid.UUID(restaurant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Restaurante inválido") from exc
    result = await db.execute(select(Restaurant).where(Restaurant.id == rid))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")

    owner_result = await db.execute(select(User).where(User.id == restaurant.owner_id))
    owner = owner_result.scalar_one_or_none()
    if owner:
        owner.is_active = True

    restaurant.status = "active"
    restaurant.is_open = True
    restaurant.public_page_enabled = True
    restaurant.rejection_reason = None
    restaurant.approved_at = datetime.now(timezone.utc)
    restaurant.approved_by = current_user.id

    membership = await db.execute(
        select(RestaurantUser).where(
            RestaurantUser.restaurant_id == restaurant.id,
            RestaurantUser.user_id == restaurant.owner_id,
        )
    )
    if not membership.scalar_one_or_none():
        db.add(RestaurantUser(
            restaurant_id=restaurant.id, user_id=restaurant.owner_id,
            role="owner", is_active=True,
        ))

    await log_action(
        db, current_user.id, "restaurant.approve", "restaurant", restaurant.id,
        {"name": restaurant.name, "owner": owner.email if owner else None},
    )
    await db.commit()

    sent, detail = (False, "Sin correo del dueño")
    if owner:
        sent, detail = await send_restaurant_welcome(
            db, owner.email, owner.name, restaurant.name, pending=False,
        )
    return {
        "status": "active",
        "restaurant_name": restaurant.name,
        "owner_email": owner.email if owner else None,
        "email_sent": sent,
        "email_detail": None if sent else detail,
    }


@router.post("/restaurant-registrations/{restaurant_id}/resend-welcome")
async def resend_welcome_email(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    try:
        rid = uuid.UUID(restaurant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Restaurante inválido") from exc
    result = await db.execute(select(Restaurant).where(Restaurant.id == rid))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if restaurant.status != "active":
        raise HTTPException(status_code=400, detail="El restaurante todavía no está aprobado")

    owner_result = await db.execute(select(User).where(User.id == restaurant.owner_id))
    owner = owner_result.scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=400, detail="El restaurante no tiene dueño registrado")

    sent, detail = await send_restaurant_welcome(
        db, owner.email, owner.name, restaurant.name, pending=False,
    )
    return {
        "email_sent": sent,
        "email_detail": None if sent else detail,
        "owner_email": owner.email,
        "restaurant_name": restaurant.name,
    }


@router.post("/restaurant-registrations/{restaurant_id}/reject")
async def reject_restaurant(
    restaurant_id: str,
    body: RestaurantApprovalRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    try:
        rid = uuid.UUID(restaurant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Restaurante inválido") from exc
    result = await db.execute(select(Restaurant).where(Restaurant.id == rid))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    owner_result = await db.execute(select(User).where(User.id == restaurant.owner_id))
    owner = owner_result.scalar_one_or_none()

    reason = (body.reason if body else None) or "Solicitud rechazada por el administrador"
    restaurant.status = "rejected"
    restaurant.rejection_reason = reason
    restaurant.is_open = False
    restaurant.public_page_enabled = False
    if owner:
        owner.is_active = False

    await log_action(
        db, current_user.id, "restaurant.reject", "restaurant", restaurant.id,
        {"name": restaurant.name, "reason": reason},
    )
    await db.commit()

    sent, detail = (False, "Sin correo del dueño")
    if owner:
        sent, detail = await send_restaurant_rejected(
            db, owner.email, owner.name, restaurant.name, reason,
        )
    return {"status": "rejected", "email_sent": sent, "email_detail": None if sent else detail}
