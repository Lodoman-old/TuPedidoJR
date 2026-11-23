"""Recordatorio semanal para clientes que dejaron de pedir."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import text

from app.core.config import settings
from app.db.session import async_session
from app.services.email_service import send_email
from app.services.order_service import get_setting_value
from app.services.push_service import send_to_user
from app.services.schedule_service import local_now
from app.services.setting_service import set_setting

logger = logging.getLogger(__name__)
WINBACK_WEEKDAY = 0  # lunes
WINBACK_HOUR = 10
MAX_PER_RUN = 200


async def maybe_send_weekly_winback() -> None:
    async with async_session() as db:
        now = await local_now(db)
        if now.weekday() != WINBACK_WEEKDAY or now.hour < WINBACK_HOUR:
            return
        today = now.date().isoformat()
        last = (await get_setting_value(db, "CUSTOMER_WINBACK_LAST_DATE", "")).strip()
        if last == today:
            return
        base = (await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)).rstrip("/")
        logo_url = f"{base}/static/logo.png" if base else "/static/logo.png"

        rows = (
            await db.execute(
                text(
                    """
                    SELECT u.id, u.name, u.email,
                           MAX(COALESCE(o.delivered_at, o.placed_at)) AS last_order
                    FROM users u
                    JOIN orders o ON o.user_id = u.id AND o.status = 'delivered'
                    WHERE u.is_superuser = false AND u.is_active = true
                    GROUP BY u.id
                    HAVING MAX(COALESCE(o.delivered_at, o.placed_at)) < :cutoff
                       AND NOT EXISTS (
                           SELECT 1 FROM orders p
                           WHERE p.user_id = u.id
                             AND p.status IN (
                               'pending', 'confirmed', 'preparing', 'ready',
                               'awaiting_courier', 'in_delivery'
                             )
                       )
                    ORDER BY last_order ASC
                    LIMIT :limit
                    """
                ),
                {"cutoff": now - timedelta(days=7), "limit": MAX_PER_RUN},
            )
        ).mappings().all()

        for user in rows:
            last_business = (
                await db.execute(
                    text(
                        """
                        SELECT r.name, r.slug
                        FROM orders o
                        JOIN restaurants r ON r.id = o.restaurant_id
                        WHERE o.user_id = :uid AND o.status = 'delivered'
                        ORDER BY COALESCE(o.delivered_at, o.placed_at) DESC
                        LIMIT 1
                        """
                    ),
                    {"uid": user["id"]},
                )
            ).mappings().first()
            business_name = last_business["name"] if last_business else "tu negocio favorito"
            path = (
                f"/r/{last_business['slug']}"
                if last_business and last_business["slug"]
                else "/web/restaurants"
            )
            link = f"{base}{path}" if base else path

            await send_to_user(
                db,
                user["id"],
                "¿Te antoja pedir de nuevo?",
                f"Hace una semana que no pides. Vuelve a {business_name} y recibe en casa.",
                {"type": "winback"},
                "amber",
            )

            if user["email"]:
                subject = "¿Te antoja pedir de nuevo?"
                text_body = (
                    f"Hola {user['name'] or ''},\n\n"
                    f"Hace una semana que no pides. Vuelve a {business_name} y recibe en casa.\n\n"
                    "Abre TuPedidoJR y pide en segundos.\n"
                )
                html = f"""
                <div style="font-family:Arial,sans-serif;background:#f4f7fb;padding:24px">
                  <div style="max-width:620px;margin:auto;background:#fff;border-radius:14px;overflow:hidden">
                    <div style="background:#0d1b2a;color:#fff;padding:20px 26px">
                      <img src="{logo_url}" alt="TuPedidoJR" style="height:38px;display:block;background:#fff;border-radius:8px;padding:5px 9px">
                      <p style="margin:10px 0 0;opacity:.85;font-size:14px">¿Te antoja pedir de nuevo?</p>
                    </div>
                    <div style="padding:26px;color:#243447;line-height:1.55">
                      <p>Hola <strong>{user['name'] or ''}</strong>,</p>
                      <p>Hace una semana que no pides. <strong>{business_name}</strong> y los demás negocios de Juventino Rosas te esperan.</p>
                      <p style="margin:24px 0 0">
                        <a href="{link}" style="background:#1B2F6B;color:#fff;padding:11px 18px;border-radius:8px;text-decoration:none">
                          Pedir ahora
                        </a>
                      </p>
                      <p style="margin-top:24px;font-size:12px;color:#6c757d">
                        Si no quieres recibir estos recordatorios, responde a este correo y te damos de baja.
                      </p>
                    </div>
                  </div>
                </div>
                """
                await send_email(db, user["email"], subject, html, text_body)

        await set_setting(db, "CUSTOMER_WINBACK_LAST_DATE", today)
        await db.commit()


async def customer_winback_loop(interval_seconds: int = 6 * 3600) -> None:
    while True:
        try:
            await maybe_send_weekly_winback()
        except Exception:
            logger.exception("No se pudo enviar el recordatorio semanal de recompra")
        await asyncio.sleep(interval_seconds)
