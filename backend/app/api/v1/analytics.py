"""Registro de visitas diarias y accesos por IP."""
import logging

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.access_log_service import record_access, role_for
from app.services.schedule_service import local_today
from app.services.security_service import client_ip

logger = logging.getLogger(__name__)
router = APIRouter()


class VisitIn(BaseModel):
    path: str | None = Field(default=None, max_length=300)


@router.post("/visit", status_code=204)
async def register_visit(
    body: VisitIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cuenta la visita y guarda IP, usuario y pantalla.

    Las métricas de audiencia siguen contando solo a clientes; el registro de
    accesos incluye también a administradores, repartidores y negocios.
    """
    try:
        role = await role_for(db, current_user)
        await record_access(
            db,
            current_user,
            role=role,
            ip=client_ip(request),
            path=body.path,
            user_agent=request.headers.get("user-agent"),
        )
        if not current_user.is_superuser:
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
