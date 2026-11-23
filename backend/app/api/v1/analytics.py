"""Registro de visitas diarias para métricas de audiencia."""
import logging

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.restaurant_user import RestaurantUser
from app.models.user import User
from app.services.schedule_service import local_today

logger = logging.getLogger(__name__)
router = APIRouter()


class VisitIn(BaseModel):
    path: str | None = Field(default=None, max_length=300)


async def _role_for(db: AsyncSession, user: User) -> str:
    if user.is_superuser:
        return "admin"
    courier = await db.execute(
        select(DeliveryPerson.id).where(DeliveryPerson.user_id == user.id).limit(1)
    )
    if courier.scalar_one_or_none():
        return "courier"
    member = await db.execute(
        select(RestaurantUser.id)
        .where(
            RestaurantUser.user_id == user.id,
            RestaurantUser.is_active.is_(True),
        )
        .limit(1)
    )
    if member.scalar_one_or_none():
        return "business"
    return "customer"


@router.post("/visit", status_code=204)
async def register_visit(
    body: VisitIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cuenta una visita por usuario y día. No afecta la navegación."""
    try:
        if current_user.is_superuser:
            return Response(status_code=204)
        role = await _role_for(db, current_user)
        today = await local_today(db)
        await db.execute(
            text(
                """
                INSERT INTO daily_visits (id, visited_on, user_id, role, views, created_at, updated_at)
                VALUES (gen_random_uuid(), :day, :user_id, :role, 1, now(), now())
                ON CONFLICT ON CONSTRAINT uq_daily_visits_user_day
                DO UPDATE SET views = daily_visits.views + 1,
                              updated_at = now()
                """
            ),
            {"day": today, "user_id": current_user.id, "role": role},
        )
        await db.commit()
    except Exception:
        logger.exception("No se pudo registrar la visita")
    return Response(status_code=204)
