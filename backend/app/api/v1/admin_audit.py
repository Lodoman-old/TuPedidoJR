"""Read-only audit log for the superuser."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter()


@router.get("/audit")
async def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(log.id),
            "user_id": str(log.user_id) if log.user_id else None,
            "user_name": user_name,
            "action": log.action,
            "entity": log.entity,
            "entity_id": log.entity_id,
            "detail": log.detail,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log, user_name in result.all()
    ]
