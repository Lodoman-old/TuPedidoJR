"""Resumen diario de seguridad por correo (una sola vez al día)."""
import asyncio
import logging
from datetime import timedelta
from html import escape

from sqlalchemy import text

from app.db.session import async_session
from app.services.email_service import send_email
from app.services.order_service import get_setting_value
from app.services.schedule_service import local_now
from app.services.setting_service import set_setting

logger = logging.getLogger(__name__)
SUMMARY_HOUR = 9  # hora local de México


async def maybe_send_daily_summary() -> None:
    async with async_session() as db:
        mode = (await get_setting_value(db, "SECURITY_EMAIL_MODE", "daily")).strip().lower()
        if mode != "daily":
            return

        now = await local_now(db)
        if now.hour < SUMMARY_HOUR:
            return
        today = now.date().isoformat()
        last = (await get_setting_value(db, "SECURITY_LAST_SUMMARY_DATE", "")).strip()
        if last == today:
            return

        since = now - timedelta(hours=24)
        row = (
            await db.execute(
                text(
                    """
                    SELECT count(*) AS total,
                           count(*) FILTER (WHERE kind = 'block') AS blocks,
                           count(DISTINCT ip) AS ips
                    FROM security_events
                    WHERE created_at >= :since
                    """
                ),
                {"since": since},
            )
        ).mappings().one()

        if not row["total"]:
            await set_setting(db, "SECURITY_LAST_SUMMARY_DATE", today)
            await db.commit()
            return

        top = (
            await db.execute(
                text(
                    """
                    SELECT ip, count(*) AS total
                    FROM security_events
                    WHERE created_at >= :since AND kind = 'block'
                    GROUP BY ip
                    ORDER BY total DESC
                    LIMIT 8
                    """
                ),
                {"since": since},
            )
        ).mappings().all()

        to = (await get_setting_value(db, "SECURITY_ALERT_EMAIL", "")).strip()
        if not to:
            to = (await get_setting_value(db, "CONTACT_EMAIL", "tupedidojr@gmail.com")).strip()
        if not to:
            return

        base = (await get_setting_value(db, "APP_PUBLIC_URL", "")).rstrip("/")
        panel = f"{base}/web/admin/security" if base else "/web/admin/security"
        logo_url = f"{base}/static/logo.png" if base else "/static/logo.png"
        rows = "".join(
            f"<tr><td style='padding:5px 0'><code>{escape(str(item['ip']))}</code></td>"
            f"<td style='padding:5px 0;text-align:right'>{int(item['total'])}</td></tr>"
            for item in top
        )
        html = f"""
        <div style="font-family:Arial,sans-serif;background:#f4f7fb;padding:24px">
          <div style="max-width:620px;margin:auto;background:#fff;border-radius:14px;overflow:hidden">
            <div style="background:#0d1b2a;color:#fff;padding:20px 26px">
              <img src="{logo_url}" alt="TuPedidoJR" style="height:38px;display:block;background:#fff;border-radius:8px;padding:5px 9px">
              <p style="margin:10px 0 0;opacity:.85;font-size:14px">Resumen diario de seguridad</p>
            </div>
            <div style="padding:26px;color:#243447;line-height:1.55">
              <p>Estos son los eventos de las últimas 24 horas:</p>
              <table style="width:100%;font-size:14px;border-collapse:collapse;margin:16px 0">
                <tr><td style="padding:6px 0;color:#64748b">Eventos totales</td><td style="text-align:right"><strong>{int(row['total'])}</strong></td></tr>
                <tr><td style="padding:6px 0;color:#64748b">IPs bloqueadas</td><td style="text-align:right"><strong>{int(row['blocks'])}</strong></td></tr>
                <tr><td style="padding:6px 0;color:#64748b">IPs distintas</td><td style="text-align:right"><strong>{int(row['ips'])}</strong></td></tr>
              </table>
              <h3 style="font-size:15px;margin:18px 0 6px">IPs con más bloqueos</h3>
              <table style="width:100%;font-size:13px;border-collapse:collapse">
                {rows or '<tr><td style="padding:6px 0;color:#64748b">Sin bloqueos en el periodo.</td></tr>'}
              </table>
              <p style="margin:24px 0 0">
                <a href="{panel}" style="background:#1B2F6B;color:#fff;padding:11px 18px;border-radius:8px;text-decoration:none">
                  Ver panel de seguridad
                </a>
              </p>
              <p style="margin-top:24px;font-size:12px;color:#6c757d">
                Puedes cambiar este resumen o desactivarlo en Seguridad → Correos de seguridad.
              </p>
            </div>
          </div>
        </div>
        """
        await send_email(
            db,
            to,
            f"TuPedidoJR: resumen de seguridad ({int(row['total'])} eventos)",
            html,
        )
        await set_setting(db, "SECURITY_LAST_SUMMARY_DATE", today)
        await db.commit()


async def security_summary_loop(interval_seconds: int = 30 * 60) -> None:
    while True:
        try:
            await maybe_send_daily_summary()
        except Exception:
            logger.exception("No se pudo enviar el resumen diario de seguridad")
        await asyncio.sleep(interval_seconds)
