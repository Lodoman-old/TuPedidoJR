"""Admin approval for restaurant self-registrations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
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
