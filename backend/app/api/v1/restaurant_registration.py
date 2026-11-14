"""Public restaurant self-registration (pending admin approval)."""
from __future__ import annotations

import re
import unicodedata
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import get_db
from app.models.restaurant import Restaurant
from app.models.restaurant_user import RestaurantUser
from app.models.user import User
from app.schemas.restaurant import RestaurantRegistrationCreate
from app.services.email_service import send_restaurant_welcome
from app.services.push_service import schedule_new_restaurant_registration

router = APIRouter()


def _slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text or "restaurante"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    index = 2
    while True:
        result = await db.execute(select(Restaurant.id).where(Restaurant.slug == candidate))
        if not result.scalar_one_or_none():
            return candidate
        candidate = f"{slug}-{index}"
        index += 1


@router.post("", status_code=201)
async def register_restaurant(
    body: RestaurantRegistrationCreate,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Ese correo ya tiene una cuenta. Inicia sesión o usa otro correo.",
        )

    user = User(
        name=body.owner_name.strip(),
        email=body.email.lower().strip(),
        phone=(body.phone or "").strip() or None,
        password_hash=hash_password(body.password),
        referral_code=uuid.uuid4().hex[:8].upper(),
        is_active=False,
    )
    db.add(user)
    await db.flush()

    restaurant = Restaurant(
        owner_id=user.id,
        name=body.restaurant_name.strip(),
        cuisine=(body.cuisine or "").strip() or None,
        slug=await _unique_slug(db, body.restaurant_name),
        address=body.address.strip(),
        phone=(body.phone or "").strip() or None,
        location=f"SRID=4326;POINT({body.lng} {body.lat})",
        status="pending",
        is_open=False,
        public_page_enabled=False,
        delivery_mode="platform",
        business_type=body.business_type,
    )
    db.add(restaurant)
    await db.flush()
    db.add(RestaurantUser(
        restaurant_id=restaurant.id,
        user_id=user.id,
        role="owner",
        is_active=True,
    ))
    await db.commit()

    schedule_new_restaurant_registration(restaurant.id)

    sent, detail = await send_restaurant_welcome(
        db, user.email, user.name, restaurant.name, pending=True,
    )
    return {
        "status": "pending",
        "restaurant_id": str(restaurant.id),
        "email_sent": sent,
        "email_detail": None if sent else detail,
        "message": (
            "Recibimos tu solicitud. Te enviamos un correo de bienvenida con los manuales. "
            "Podrás iniciar sesión cuando el restaurante sea aprobado."
            if sent else
            "Recibimos tu solicitud. Podrás iniciar sesión cuando el restaurante sea aprobado."
        ),
    }
