import asyncio
import json
import logging
import os
import time

import httpx
from jose import jwt
from sqlalchemy import select, text

from app.db.session import async_session
from app.core.config import settings
from app.models.delivery_person import DeliveryPerson
from app.models.mandado import Mandado
from app.models.order import Order
from app.models.push_token import PushToken
from app.models.restaurant import Restaurant
from app.models.restaurant_user import RestaurantUser
from app.models.setting import Setting
from app.models.user import User
from app.services.restaurant_access import ORDER_ROLES

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

PUSH_ENABLED = "PUSH_ENABLED"
FCM_SERVICE_ACCOUNT_JSON = "FCM_SERVICE_ACCOUNT_JSON"
FCM_WEB_CONFIG_JSON = "FCM_WEB_CONFIG_JSON"
FCM_VAPID_KEY = "FCM_VAPID_KEY"
FCM_ANDROID_CONFIG_JSON = "FCM_ANDROID_CONFIG_JSON"

STATUS_MESSAGES = {    "confirmed": ("Pedido confirmado", "El restaurante confirmó tu pedido."),
    "awaiting_courier": (
        "Esperando repartidor",
        "Tu pedido está lejos: un repartidor debe aceptarlo antes de que el restaurante lo prepare.",
    ),
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

# Estilo visual de la notificación: imagen grande y color de acento.
STYLE_IMAGES = {
    "green": ("/static/notif_green.png", "#2E7D32"),
    "amber": ("/static/notif_amber.png", "#F9A825"),
    "red": ("/static/notif_red.png", "#C62828"),
}
STATUS_STYLES = {
    "confirmed": "amber",
    "awaiting_courier": "amber",
    "preparing": "amber",
    "ready": "red",
    "in_delivery": "amber",
    "picked_up": "amber",
    "delivered": "green",
    "cancelled": "red",
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
    style: str | None = None,
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

    base_url = (settings.APP_URL or "").rstrip("/")
    image_path, accent = STYLE_IMAGES.get(
        style or "", ("/static/logo_notification_circle.png", "#1B2F6B")
    )
    logo_url = f"{base_url}{image_path}" if base_url else image_path
    event_type = str((data or {}).get("type") or "")
    priority_alert = event_type in ("new_order", "available_order")
    android_notification: dict = {
        "icon": "ic_stat_tup",
        "color": accent,
        "channel_id": "orders_high_v2" if priority_alert else "orders_high",
    }
    if priority_alert:
        android_notification["sound"] = "order_alert"
    if base_url:
        android_notification["image"] = logo_url

    async with httpx.AsyncClient(timeout=15) as client:
        for push_token in tokens:
            payload = {
                "message": {
                    "token": push_token.token,
                    "notification": {"title": title, "body": body},
                    "data": payload_data,
                    "android": {
                        "priority": "high",
                        "notification": android_notification,
                    },
                    "webpush": {
                        "headers": {"Urgency": "high"},
                        "notification": {"icon": logo_url},
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


async def send_to_user(db, user_id, title: str, body: str, data: dict | None = None, style: str | None = None) -> dict:
    result = await db.execute(
        select(PushToken).where(PushToken.user_id == user_id, PushToken.is_active.is_(True))
    )
    return await send_to_tokens(db, list(result.scalars().all()), title, body, data, style)


async def _eta_minutes(db, order) -> int | None:
    """Tiempo estimado en minutos usando la ruta real hasta el cliente."""
    try:
        row = (
            await db.execute(
                text(
                    "SELECT "
                    "ST_Y(dp.current_location::geometry) AS dlat, "
                    "ST_X(dp.current_location::geometry) AS dlng, "
                    "ST_Y(o.delivery_location::geometry) AS olat, "
                    "ST_X(o.delivery_location::geometry) AS olng "
                    "FROM delivery_persons dp, orders o "
                    "WHERE dp.id = :dp AND o.id = :oid"
                ),
                {"dp": order.delivery_person_id, "oid": order.id},
            )
        ).mappings().first()
        if not row or row["dlat"] is None or row["dlng"] is None:
            return None
        from app.services.route_service import route_info

        _distance, duration_min, _source = await route_info(
            db,
            float(row["dlat"]),
            float(row["dlng"]),
            float(row["olat"]),
            float(row["olng"]),
        )
        return max(2, round(duration_min))
    except Exception:
        return None


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
            if status in ("in_delivery", "picked_up") and order.delivery_person_id:
                minutes = await _eta_minutes(db, order)
                if minutes:
                    body = f"{body} Llega en aproximadamente {minutes} min."
            if status == "cancelled":
                reason = (order.cancellation_reason or "").strip()
                if reason:
                    body = f"Tu pedido fue cancelado: {reason}."
                if order.refund_status == "pending" and order.payment_method == "transfer":
                    body += (
                        " Para devolverte el dinero, captura tu cuenta bancaria "
                        "en el detalle del pedido."
                    )
            await send_to_user(
                db,
                order.user_id,
                title,
                body,
                {"type": "order_status", "order_id": str(order.id), "status": status},
                STATUS_STYLES.get(status),
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
            # Los pedidos lejanos no se muestran al restaurante hasta que un
            # repartidor los acepte.
            if order.requires_courier_approval and not order.delivery_person_id:
                return
            resto_result = await db.execute(
                select(Restaurant).where(Restaurant.id == order.restaurant_id)
            )
            restaurant = resto_result.scalar_one_or_none()
            if not restaurant:
                return
            members_result = await db.execute(
                select(RestaurantUser.user_id).where(
                    RestaurantUser.restaurant_id == restaurant.id,
                    RestaurantUser.is_active.is_(True),
                    RestaurantUser.role.in_(ORDER_ROLES),
                )
            )
            user_ids = {restaurant.owner_id, *members_result.scalars().all()}
            items_count = sum(int(item.quantity or 0) for item in order.items) or 1
            total = float(order.total or 0)
            for user_id in user_ids:
                await send_to_user(
                    db,
                    user_id,
                    "Nuevo pedido",
                    f"{restaurant.name}: {items_count} artículo(s) · ${total:.2f}",
                    {"type": "new_order", "order_id": str(order.id)},
                    "green",
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


async def notify_new_restaurant_registration(restaurant_id: str) -> None:
    """Notify every active administrator that a restaurant is waiting for approval."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
            restaurant = result.scalar_one_or_none()
            if not restaurant:
                return
            admins = await db.execute(
                select(User.id).where(
                    User.is_superuser.is_(True),
                    User.is_active.is_(True),
                )
            )
            for admin_id in admins.scalars().all():
                await send_to_user(
                    db,
                    admin_id,
                    "Nueva solicitud de restaurante",
                    f"{restaurant.name} está esperando aprobación.",
                    {
                        "type": "restaurant_registration",
                        "restaurant_id": str(restaurant.id),
                    },
                )
    except Exception:
        logger.exception("Push restaurant-registration notification failed for %s", restaurant_id)


async def notify_arrival(order_id: str) -> None:
    """El repartidor llegó a la ubicación del cliente."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                return
            await send_to_user(
                db,
                order.user_id,
                "Tu pedido está cerca",
                "El repartidor está a pocos metros de tu ubicación.",
                {"type": "order_arrival", "order_id": str(order.id)},
                "green",
            )
    except Exception:
        logger.exception("Push arrival notification failed for %s", order_id)


async def notify_available_order(order_id: str, ready: bool = False) -> None:
    """Avisa a los repartidores disponibles que hay un pedido por tomar."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                return
            resto = await db.execute(
                select(Restaurant).where(Restaurant.id == order.restaurant_id)
            )
            restaurant = resto.scalar_one_or_none()

            couriers = await db.execute(
                select(DeliveryPerson).where(DeliveryPerson.is_available.is_(True))
            )
            people = list(couriers.scalars().all())
            if not people:
                couriers = await db.execute(select(DeliveryPerson))
                people = list(couriers.scalars().all())

            title = "Pedido listo para recoger" if ready else "Pedido disponible"
            name = restaurant.name if restaurant else "Restaurante"
            earnings = float(order.delivery_earnings or 0)
            body = f"{name} · ${earnings:.2f} por el reparto"
            for dp in people:
                await send_to_user(
                    db,
                    dp.user_id,
                    title,
                    body,
                    {"type": "available_order", "order_id": str(order.id)},
                    "red" if ready else "amber",
                )
    except Exception:
        logger.exception("Push available-order notification failed for %s", order_id)


async def notify_courier_assigned(order_id: str) -> None:
    """Confirma al repartidor que tomó el pedido y avisa al restaurante."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order or not order.delivery_person_id:
                return
            resto = await db.execute(
                select(Restaurant).where(Restaurant.id == order.restaurant_id)
            )
            restaurant = resto.scalar_one_or_none()
            name = restaurant.name if restaurant else "Restaurante"
            dp = await db.get(DeliveryPerson, order.delivery_person_id)
            reserved = order.status in ("pending", "confirmed")
            if dp:
                await send_to_user(
                    db,
                    dp.user_id,
                    "Pedido reservado" if reserved else "Pedido asignado",
                    (
                        f"{name}: apartaste este pedido lejano. El restaurante todavía "
                        "debe confirmarlo; te avisaremos cuando puedas recogerlo."
                        if reserved
                        else f"{name}: espera a que el restaurante termine de prepararlo. "
                        "Te avisaremos cuando esté listo."
                    ),
                    {"type": "assigned_order", "order_id": str(order.id)},
                    "green",
                )
            if not restaurant:
                return
            members = await db.execute(
                select(RestaurantUser.user_id).where(
                    RestaurantUser.restaurant_id == restaurant.id,
                    RestaurantUser.is_active.is_(True),
                    RestaurantUser.role.in_(ORDER_ROLES),
                )
            )
            user_ids = {restaurant.owner_id, *members.scalars().all()}
            for user_id in user_ids:
                await send_to_user(
                    db,
                    user_id,
                    "Nuevo pedido con repartidor" if reserved else "Repartidor asignado",
                    (
                        f"{name}: un repartidor aceptó este pedido lejano. "
                        "Confírmalo para comenzar a prepararlo."
                        if reserved
                        else f"{name}: un repartidor aceptó el pedido. Ya puedes prepararlo."
                    ),
                    {"type": "new_order", "order_id": str(order.id)},
                    "green",
                )
    except Exception:
        logger.exception("Push courier-assigned notification failed for %s", order_id)


async def notify_courier_order_ready(order_id: str) -> None:
    """Avisa al repartidor asignado que el pedido ya está listo para recoger."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order or not order.delivery_person_id:
                return
            dp = await db.get(DeliveryPerson, order.delivery_person_id)
            if not dp:
                return
            resto = await db.execute(
                select(Restaurant).where(Restaurant.id == order.restaurant_id)
            )
            restaurant = resto.scalar_one_or_none()
            name = restaurant.name if restaurant else "Restaurante"
            await send_to_user(
                db,
                dp.user_id,
                "Pedido listo para recoger",
                f"{name}: el pedido #${str(order.id)[:8]} ya está listo.",
                {"type": "assigned_order", "order_id": str(order.id)},
                "red",
            )
    except Exception:
        logger.exception("Push courier-ready notification failed for %s", order_id)


def schedule_order_status(order_id: str, status: str) -> None:
    try:
        asyncio.create_task(notify_order_status(order_id, status))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_available_order(order_id: str, ready: bool = False) -> None:
    try:
        asyncio.create_task(notify_available_order(order_id, ready))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_courier_assigned(order_id: str) -> None:
    try:
        asyncio.create_task(notify_courier_assigned(order_id))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_courier_ready(order_id: str) -> None:
    try:
        asyncio.create_task(notify_courier_order_ready(order_id))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_arrival(order_id: str) -> None:
    try:
        asyncio.create_task(notify_arrival(order_id))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_new_order(order_id: str) -> None:
    try:
        asyncio.create_task(notify_new_order(order_id))
    except RuntimeError:
        logger.debug("No event loop for push notification")


def schedule_new_restaurant_registration(restaurant_id: str) -> None:
    try:
        asyncio.create_task(notify_new_restaurant_registration(restaurant_id))
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


async def bootstrap_push_settings() -> None:
    """Carga FCM desde variables de entorno en un despliegue nuevo.

    Solo escribe valores que todavía no existan en la base, para no pisar
    cambios hechos desde /web/admin/push.
    """
    service_account_raw = (os.getenv("FCM_SERVICE_ACCOUNT_JSON") or "").strip()
    android_raw = (os.getenv("PUSH_ANDROID_CONFIG_JSON") or "").strip()
    web_raw = (os.getenv("PUSH_WEB_CONFIG_JSON") or "").strip()
    vapid_raw = (os.getenv("PUSH_VAPID_KEY") or "").strip()
    enabled_raw = (os.getenv("PUSH_ENABLED") or "").strip().lower()

    if not any((service_account_raw, android_raw, web_raw, vapid_raw, enabled_raw)):
        return

    try:
        async with async_session() as db:
            if service_account_raw and not await get_setting(db, FCM_SERVICE_ACCOUNT_JSON):
                parsed = _load_json(service_account_raw)
                if parsed and all(parsed.get(key) for key in ("client_email", "private_key", "project_id")):
                    await set_setting(
                        db,
                        FCM_SERVICE_ACCOUNT_JSON,
                        json.dumps(parsed),
                        "Firebase service account (privado)",
                    )
                    logger.info("FCM: service account cargada desde variables de entorno")
                else:
                    logger.warning("FCM: FCM_SERVICE_ACCOUNT_JSON no tiene los campos requeridos")

            if android_raw and not await get_setting(db, FCM_ANDROID_CONFIG_JSON):
                parsed = _load_json(android_raw)
                if parsed:
                    await set_setting(
                        db,
                        FCM_ANDROID_CONFIG_JSON,
                        json.dumps(parsed),
                        "Firebase Android client config (público, para APK)",
                    )
                    logger.info("FCM: configuración Android cargada desde variables de entorno")

            if web_raw and not await get_setting(db, FCM_WEB_CONFIG_JSON):
                parsed = _load_json(web_raw)
                if parsed:
                    await set_setting(
                        db,
                        FCM_WEB_CONFIG_JSON,
                        json.dumps(parsed),
                        "Firebase web config (público, para PWA)",
                    )
                    logger.info("FCM: configuración web cargada desde variables de entorno")

            if vapid_raw and not await get_setting(db, FCM_VAPID_KEY):
                await set_setting(
                    db,
                    FCM_VAPID_KEY,
                    vapid_raw,
                    "VAPID key pública para PWA",
                )
                logger.info("FCM: VAPID cargada desde variables de entorno")

            await db.flush()
            current_enabled = await get_setting(db, PUSH_ENABLED)
            if not current_enabled:
                if enabled_raw in ("1", "true", "yes", "si", "sí"):
                    if await get_setting(db, FCM_SERVICE_ACCOUNT_JSON):
                        await set_setting(
                            db,
                            PUSH_ENABLED,
                            "true",
                            "Activa o desactiva las notificaciones push",
                        )
                        logger.info("FCM: push activado desde variables de entorno")
                    else:
                        logger.warning("FCM: PUSH_ENABLED=true pero falta la service account")
                elif enabled_raw in ("0", "false", "no"):
                    await set_setting(
                        db,
                        PUSH_ENABLED,
                        "false",
                        "Activa o desactiva las notificaciones push",
                    )
            await db.commit()
    except Exception:
        logger.exception("FCM: no se pudo inicializar desde variables de entorno")

