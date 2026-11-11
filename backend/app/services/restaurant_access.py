"""Restaurant membership checks and role helpers."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.restaurant import Restaurant
from app.models.restaurant_user import RestaurantUser
from app.models.user import User

ROLE_LABELS = {
    "owner": "Dueño",
    "manager": "Encargado",
    "staff": "Personal",
    "cashier": "Cajero",
    "kitchen": "Cocina",
}

ROLE_LEVEL = {"cashier": 1, "kitchen": 1, "staff": 2, "manager": 3, "owner": 4}
ORDER_ROLES = {"owner", "manager", "staff", "cashier", "kitchen"}
MANAGE_ROLES = {"owner", "manager"}
FINANCE_ROLES = {"owner", "manager"}
OWNER_ROLES = {"owner"}


async def restaurant_role(db: AsyncSession, restaurant_id, user: User) -> str | None:
    if user.is_superuser:
        return "admin"
    result = await db.execute(
        select(RestaurantUser.role).where(
            RestaurantUser.restaurant_id == restaurant_id,
            RestaurantUser.user_id == user.id,
            RestaurantUser.is_active.is_(True),
        )
    )
    role = result.scalar_one_or_none()
    if role:
        return role
    result = await db.execute(
        select(Restaurant.owner_id).where(Restaurant.id == restaurant_id)
    )
    owner_id = result.scalar_one_or_none()
    return "owner" if owner_id == user.id else None


async def have_role(
    db: AsyncSession,
    restaurant_id,
    user: User,
    allowed: set[str] | None = None,
) -> bool:
    role = await restaurant_role(db, restaurant_id, user)
    if role is None:
        return False
    if role == "admin":
        return True
    return allowed is None or role in allowed


async def require_role(
    db: AsyncSession,
    restaurant_id,
    user: User,
    allowed: set[str] | None = None,
    detail: str = "No tienes acceso a este restaurante",
):
    if not await have_role(db, restaurant_id, user, allowed):
        raise HTTPException(status_code=403, detail=detail)


async def my_restaurants(db: AsyncSession, user: User) -> list[Restaurant]:
    if user.is_superuser:
        result = await db.execute(select(Restaurant).order_by(Restaurant.name))
        return list(result.scalars().all())
    result = await db.execute(
        select(Restaurant)
        .join(RestaurantUser, RestaurantUser.restaurant_id == Restaurant.id)
        .where(
            RestaurantUser.user_id == user.id,
            RestaurantUser.is_active.is_(True),
        )
        .options(selectinload(Restaurant.categories), selectinload(Restaurant.menu))
        .order_by(Restaurant.name)
    )
    restaurants = list(result.scalars().unique().all())
    if restaurants:
        return restaurants
    result = await db.execute(
        select(Restaurant).where(Restaurant.owner_id == user.id)
    )
    return list(result.scalars().all())


async def my_restaurant_ids(db: AsyncSession, user: User) -> list:
    return [r.id for r in await my_restaurants(db, user)]
