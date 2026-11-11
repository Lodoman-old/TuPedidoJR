import asyncio
import json
import logging
import time

import httpx
from jose import jwt
from sqlalchemy import select

from app.db.session import async_session
from app.models.delivery_person import DeliveryPerson
from app.models.mandado import Mandado
from app.models.order import Order
from app.models.push_token import PushToken
from app.models.restaurant import Restaurant
from app.models.setting import Setting

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

PUSH_ENABLED = "PUSH_ENABLED"
FCM_SERVICE_ACCOUNT_JSON = "FCM_SERVICE_ACCOUNT_JSON"
FCM_WEB_CONFIG_JSON = "FCM_WEB_CONFIG_JSON"
FCM_VAPID_KEY = "FCM_VAPID_KEY"
FCM_ANDROID_CONFIG_JSON = "FCM_ANDROID_CONFIG_JSON"

STATUS_MESSAGES = {
    "confirmed": ("Pedido confirmado", "El restaurante confirmó tu pedido."),
    "preparing": ("Preparando tu pedido", "El restaurante está preparando tu pedido."),
    "ready": ("Pedido listo", "Tu pedido está listo y espera al repartidor."),
    "in_delivery": ("Repartidor en camino", "Tu pedido ya va en camino."),
    "picked_up": ("Pedido recogido", "El repartidor recogió tu pedido."),
    "delivered": ("Pedido entregado", "¡Buen provecho! Tu pedido fue entregado."),
    "cancelled": ("Pedido cancelado", "Tu pedido fue cancelado."),
}

MANDADO_MESSAGES = {
    "accepted": ("Mandado aceptado", "Un repartidor aceptó tu mandado."),
    "purchased": ("Compra realizada", "El repartidor realizó la compra de tu mandado."),
    "completed": ("Mandado entregado", "Tu mandado fue entregado."),
    "cancelled": ("Mandado cancelado", "Tu mandado fue cancelado."),
}

# access_token cache: project_id -> (token, expires_at_epoch)
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


async def get_setting(db, key: str, default: str = "") -> str:
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting and setting.value is not None else default


async def set_setting(db, key: str, value: str, description: str | None = None) -> None:
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
        if description:
            setting.description = description
    else:
        db.add(Setting(key=key, value=value, description=description))


def _load_json(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


async def get_public_config(db) -> dict:
    enabled = (await get_setting(db, PUSH_ENABLED, "false")).lower() == "true"
    web_config = _load_json(await get_setting(db, FCM_WEB_CONFIG_JSON))
    android_config = _load_json(await get_setting(db, FCM_ANDROID_CONFIG_JSON))
    vapid_key = await get_setting(db, FCM_VAPID_KEY) or None
    if not enabled:
        return {"enabled": False, "web_config": None, "android_config": None, "vapid_key": None}
    return {
        "enabled": True,
        "web_config": web_config,
        "android_config": android_config,
        "vapid_key": vapid_key,
    }


async def get_admin_config(db) -> dict:
    enabled = (await get_setting(db, PUSH_ENABLED, "false")).lower() == "true"
    service_account = _load_json(await get_setting(db, FCM_SERVICE_ACCOUNT_JSON))
    web_config = _load_json(await get_setting(db, FCM_WEB_CONFIG_JSON))
    android_config = _load_json(await get_setting(db, FCM_ANDROID_CONFIG_JSON))
    vapid_key = await get_setting(db, FCM_VAPID_KEY) or None
    tokens_count = len(
        (await db.execute(select(PushToken.id).where(PushToken.is_active.is_(True)))).scalars().all()
    )
    return {
        "enabled": enabled,
        "has_service_account": bool(service_account),
        "project_id": (service_account or {}).get("project_id"),
        "web_config": web_config,
        "android_config": android_config,
        "vapid_key": vapid_key,
        "tokens_count": tokens_count,
    }


async def _get_access_token(service_account: dict) -> str:
    project_id = service_account.get("project_id")
    if not project_id:
        raise ValueError("El service account no tiene project_id")

    cached = _TOKEN_CACHE.get(project_id)
    if cached and cached[1] > time.time() + 30:
        return cached[0]

    now = int(time.time())
    claims = {
        "iss": service_account["client_email"],
        "scope": FCM_SCOPE,
        "aud": service_account.get("token_uri", "https://oauth2.googleapis.com/token"),
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jwt.encode(claims, service_account["private_key"], algorithm="RS256")

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            claims["aud"],
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(f"No se pudo obtener token de Google: {response.text[:300]}")

    data = response.json()
    token = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    _TOKEN_CACHE[project_id] = (token, time.time() + expires_in)
    return token


async def send_to_tokens(
    db,
    tokens: list[PushToken],
    title: str,
    body: str,
    data: dict | None = None,
) -> dict:
    """Send an FCM notification. Returns {sent, failed, deactivated}."""
    stats = {"sent": 0, "failed": 0, "deactivated": 0}
    if not tokens:
        return stats

    enabled = (await get_setting(db, PUSH_ENABLED, "false")).lower() == "true"
    service_account = _load_json(await get_setting(db, FCM_SERVICE_ACCOUNT_JSON))
    if not enabled or not service_account:
        return stats

    try:
        access_token = await _get_access_token(service_account)
    except Exception as exc:
        logger.error("FCM auth failed: %s", exc)
        return stats

    project_id = service_account["project_id"]
    url = FCM_ENDPOINT.format(project_id=project_id)
    payload_data = {str(k): str(v) for k, v in (data or {}).items()}

    async with httpx.AsyncClient(timeout=15) as client:
        for push_token in tokens:
            payload = {
                "message": {
                    "token": push_token.token,
                    "notification": {"title": title, "body": body},
                    "data": payload_data,
                    "android": {"priority": "high"},
                    "webpush": {
                        "headers": {"Urgency": "high"},
                        "notification": {"icon": "/static/logo.png"},
                    },
                }
            }
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json=payload,
                )
                if response.status_code < 400:
                    stats["sent"] += 1
                    continue

                stats["failed"] += 1
                error_text = response.text
                if response.status_code == 404 or "UNREGISTERED" in error_text or "NOT_FOUND" in error_text:
                    push_token.is_active = False
                    stats["deactivated"] += 1
                else:
                    logger.warning("FCM send failed (%s): %s", response.status_code, error_text[:300])
            except Exception as exc:
                stats["failed"] += 1
                logger.warning("FCM send exception: %s", exc)

    await db.commit()
    return stats


async def send_to_user(db, user_id, title: str, body: str, data: dict | None = None) -> dict:
    result = await db.execute(
        select(PushToken).where(PushToken.user_id == user_id, PushToken.is_active.is_(True))
    )
    return await send_to_tokens(db, list(result.scalars().all()), title, body, data)


async def notify_order_status(order_id: str, status: str) -> None:
    """Fire-and-forget notification to the customer when an order changes status."""
    if status not in STATUS_MESSAGES:
        return
    title, body = STATUS_MESSAGES[status]
    try:
        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                return
            await send_to_user(
                db,
                order.user_id,
                title,
                body,
                {"type": "order_status", "order_id": str(order.id), "status": status},
            )
    except Exception:
        logger.exception("Push notification failed for order %s", order_id)


async def notify_new_order(order_id: str) -> None:
    """Notify the restaurant owner that a new order was placed."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                return
            resto_result = await db.execute(
                select(Restaurant).where(Restaurant.id == order.restaurant_id)
            )
            restaurant = resto_result.scalar_one_or_none()
            if not restaurant:
                return
            await send_to_user(
                db,
                restaurant.owner_id,
                "Nuevo pedido",
                f"Tienes un nuevo pedido en {restaurant.name}.",
                {"type": "new_order", "order_id": str(order.id)},
            )
    except Exception:
        logger.exception("Push new-order notification failed for %s", order_id)


async def notify_new_mandado(mandado_id: str) -> None:
    """Notify every mandadero that a new mandado is available."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
            mandado = result.scalar_one_or_none()
            if not mandado or mandado.status != "pending":
                return
            dp_result = await db.execute(
                select(DeliveryPerson).where(DeliveryPerson.is_mandadero.is_(True))
            )
            for dp in dp_result.scalars().all():
                await send_to_user(
                    db,
                    dp.user_id,
                    "Nuevo mandado disponible",
                    (mandado.description or "Tienes un mandado disponible")[:120],
                    {"type": "new_mandado", "mandado_id": str(mandado.id)},
                )
    except Exception:
        logger.exception("Push new-mandado notification failed for %s", mandado_id)


async def notify_mandado_status(mandado_id: str, status: str) -> None:
    if status not in MANDADO_MESSAGES:
        return
    title, body = MANDADO_MESSAGES[status]
    try:
        async with async_session() as db:
            result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
            mandado = result.scalar_one_or_none()
            if not mandado:
                return
            await send_to_user(
                db,
                mandado.user_id,
                title,
                body,
                {"type": "mandado_status", "mandado_id": str(mandado.id), "status": status},
            )
    except Exception:
        logger.exception("Push mandado notification failed for %s", mandado_id)


def schedule_order_status(order_id: str, status: str) -> None:
    try:
        asyncio.create_task(notify_order_status(order_id, status))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_new_order(order_id: str) -> None:
    try:
        asyncio.create_task(notify_new_order(order_id))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_new_mandado(mandado_id: str) -> None:
    try:
        asyncio.create_task(notify_new_mandado(mandado_id))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_mandado_status(mandado_id: str, status: str) -> None:
    try:
        asyncio.create_task(notify_mandado_status(mandado_id, status))
    except RuntimeError:
        logger.debug("No event loop for push notification")
