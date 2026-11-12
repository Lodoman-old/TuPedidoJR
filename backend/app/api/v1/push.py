import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_superuser
from app.db.session import get_db
from app.models.push_token import PushToken
from app.models.user import User
from app.schemas.push import (
    PushAdminConfigIn,
    PushAdminConfigOut,
    PushPublicConfig,
    PushTestRequest,
    PushTokenRegister,
)
from app.services import push_service

router = APIRouter()


@router.get("/config", response_model=PushPublicConfig)
async def public_config(db: AsyncSession = Depends(get_db)):
    """Public Firebase web config (no secrets) so the PWA can get a token."""
    return await push_service.get_public_config(db)


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def register_token(
    body: PushTokenRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(PushToken).where(PushToken.token == body.token))
    push_token = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if push_token:
        push_token.user_id = current_user.id
        push_token.platform = body.platform
        push_token.device_label = body.device_label
        push_token.is_active = True
        push_token.last_seen_at = now
    else:
        push_token = PushToken(
            user_id=current_user.id,
            token=body.token,
            platform=body.platform,
            device_label=body.device_label,
            is_active=True,
            last_seen_at=now,
        )
        db.add(push_token)
    await db.commit()
    return {"ok": True}


@router.delete("/tokens", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_token(
    token: str = Query(..., min_length=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PushToken).where(
            PushToken.token == token,
            PushToken.user_id == current_user.id,
        )
    )
    push_token = result.scalar_one_or_none()
    if push_token:
        push_token.is_active = False
        await db.commit()


@router.get("/admin/config", response_model=PushAdminConfigOut)
async def admin_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superuser),
):
    return await push_service.get_admin_config(db)


@router.put("/admin/config", response_model=PushAdminConfigOut)
async def update_admin_config(
    body: PushAdminConfigIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superuser),
):
    if body.service_account_json:
        try:
            service_account = json.loads(body.service_account_json)
        except ValueError:
            raise HTTPException(status_code=400, detail="El service account no es un JSON válido")
        missing = [k for k in ("client_email", "private_key", "project_id") if not service_account.get(k)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Faltan campos en el service account: {', '.join(missing)}",
            )
        await push_service.set_setting(
            db,
            push_service.FCM_SERVICE_ACCOUNT_JSON,
            json.dumps(service_account),
            "Firebase service account (privado)",
        )

    if body.web_config_json:
        try:
            web_config = json.loads(body.web_config_json)
        except ValueError:
            raise HTTPException(status_code=400, detail="La configuración web no es un JSON válido")
        if not isinstance(web_config, dict):
            raise HTTPException(status_code=400, detail="La configuración web debe ser un objeto JSON")
        await push_service.set_setting(
            db,
            push_service.FCM_WEB_CONFIG_JSON,
            json.dumps(web_config),
            "Firebase web config (público, para PWA)",
        )

    if body.android_config_json:
        try:
            android_config = json.loads(body.android_config_json)
        except ValueError:
            raise HTTPException(status_code=400, detail="La configuración Android no es un JSON válido")
        if not isinstance(android_config, dict):
            raise HTTPException(status_code=400, detail="La configuración Android debe ser un objeto JSON")
        await push_service.set_setting(
            db,
            push_service.FCM_ANDROID_CONFIG_JSON,
            json.dumps(android_config),
            "Firebase Android client config (público, para APK)",
        )

    if body.vapid_key is not None:
        await push_service.set_setting(
            db,
            push_service.FCM_VAPID_KEY,
            body.vapid_key.strip(),
            "VAPID key pública para PWA",
        )

    await db.flush()

    if body.enabled:
        service_account = await push_service.get_setting(db, push_service.FCM_SERVICE_ACCOUNT_JSON)
        if not service_account:
            raise HTTPException(
                status_code=400,
                detail="Para activar las notificaciones primero carga el service account de Firebase",
            )

    await push_service.set_setting(
        db,
        push_service.PUSH_ENABLED,
        "true" if body.enabled else "false",
        "Activa o desactiva las notificaciones push",
    )
    await db.commit()
    return await push_service.get_admin_config(db)


@router.post("/admin/test")
async def send_test_push(
    body: PushTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    if body.only_self:
        stats = await push_service.send_to_user(
            db,
            current_user.id,
            body.title,
            body.body,
            {"type": "test", "user_id": str(current_user.id)},
            body.style,
        )
    else:
        result = await db.execute(select(PushToken).where(PushToken.is_active.is_(True)))
        stats = await push_service.send_to_tokens(
            db,
            list(result.scalars().all()),
            body.title,
            body.body,
            {"type": "test"},
            body.style,
        )
    return stats
