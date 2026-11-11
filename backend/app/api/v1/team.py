"""Restaurant team users and roles."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import hash_password
from app.db.session import get_db
from app.models.restaurant import Restaurant
from app.models.restaurant_user import RestaurantUser
from app.models.user import User
from app.schemas.restaurant import TeamMemberCreate, TeamMemberOut, TeamMemberUpdate
from app.services.audit_service import log_action
from app.services.email_service import send_team_welcome
from app.services.restaurant_access import OWNER_ROLES, ROLE_LABELS, require_role

router = APIRouter()


async def _restaurant(db: AsyncSession, restaurant_id: str, user: User) -> Restaurant:
    try:
        rid = uuid.UUID(restaurant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Restaurante inválido") from exc
    result = await db.execute(select(Restaurant).where(Restaurant.id == rid))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    await require_role(db, restaurant.id, user, OWNER_ROLES)
    return restaurant


@router.get("", response_model=list[TeamMemberOut])
async def list_team(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id, current_user)
    result = await db.execute(
        select(RestaurantUser, User)
        .join(User, User.id == RestaurantUser.user_id)
        .where(RestaurantUser.restaurant_id == restaurant.id)
        .order_by(RestaurantUser.role, User.name)
    )
    return [
        TeamMemberOut(
            id=membership.id,
            user_id=user.id,
            name=user.name,
            email=user.email,
            role=membership.role,
            is_active=membership.is_active,
            created_at=membership.created_at,
        )
        for membership, user in result.all()
    ]


@router.post("", response_model=TeamMemberOut, status_code=201)
async def add_team_member(
    restaurant_id: str,
    body: TeamMemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id, current_user)
    email = body.email.lower().strip()
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ese correo ya tiene una cuenta")

    user = User(
        name=body.name.strip(),
        email=email,
        password_hash=hash_password(body.password),
        referral_code=uuid.uuid4().hex[:8].upper(),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    membership = RestaurantUser(
        restaurant_id=restaurant.id,
        user_id=user.id,
        role=body.role,
        is_active=True,
    )
    db.add(membership)
    await log_action(
        db, current_user.id, "team.add", "restaurant", restaurant.id,
        {"email": email, "role": body.role},
    )
    await db.commit()
    await db.refresh(membership)

    await send_team_welcome(
        db, email, user.name, restaurant.name,
        ROLE_LABELS.get(body.role, body.role), body.password,
    )
    return TeamMemberOut(
        id=membership.id,
        user_id=user.id,
        name=user.name,
        email=user.email,
        role=membership.role,
        is_active=membership.is_active,
        created_at=membership.created_at,
    )


@router.patch("/{member_id}", response_model=TeamMemberOut)
async def update_team_member(
    restaurant_id: str,
    member_id: str,
    body: TeamMemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id, current_user)
    result = await db.execute(
        select(RestaurantUser, User)
        .join(User, User.id == RestaurantUser.user_id)
        .where(
            RestaurantUser.id == member_id,
            RestaurantUser.restaurant_id == restaurant.id,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Usuario del equipo no encontrado")
    membership, user = row
    if membership.role == "owner":
        raise HTTPException(status_code=400, detail="No puedes modificar al dueño")
    if body.role is not None:
        membership.role = body.role
    if body.is_active is not None:
        membership.is_active = body.is_active
        user.is_active = body.is_active
    await log_action(
        db, current_user.id, "team.update", "restaurant", restaurant.id,
        {"email": user.email, "role": membership.role, "active": membership.is_active},
    )
    await db.commit()
    return TeamMemberOut(
        id=membership.id,
        user_id=user.id,
        name=user.name,
        email=user.email,
        role=membership.role,
        is_active=membership.is_active,
        created_at=membership.created_at,
    )


@router.delete("/{member_id}", status_code=204)
async def remove_team_member(
    restaurant_id: str,
    member_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id, current_user)
    result = await db.execute(
        select(RestaurantUser, User)
        .join(User, User.id == RestaurantUser.user_id)
        .where(
            RestaurantUser.id == member_id,
            RestaurantUser.restaurant_id == restaurant.id,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Usuario del equipo no encontrado")
    membership, user = row
    if membership.role == "owner":
        raise HTTPException(status_code=400, detail="No puedes eliminar al dueño")
    await db.delete(membership)
    await db.flush()
    remaining = await db.execute(
        select(RestaurantUser.id).where(
            RestaurantUser.user_id == user.id,
            RestaurantUser.is_active.is_(True),
        )
    )
    if not remaining.first():
        user.is_active = False
    await log_action(
        db, current_user.id, "team.remove", "restaurant", restaurant.id,
        {"email": user.email},
    )
    await db.commit()
    return None
