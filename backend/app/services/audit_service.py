from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    user_id,
    action: str,
    entity: str | None = None,
    entity_id: str | None = None,
    detail: dict | None = None,
):
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail,
    ))
