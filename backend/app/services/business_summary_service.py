"""Resumen semanal para negocios: ventas, comisiones y productos top."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import text

from app.core.config import settings
from app.db.session import async_session
from app.services.email_service import send_email
from app.services.order_service import get_setting_value
from app.services.schedule_service import local_now
from app.services.setting_service import set_setting

logger = logging.getLogger(__name__)
SUMMARY_WEEKDAY = 0  # lunes
SUMMARY_HOUR = 8

BUSINESS_STATS_SQL = """
SELECT count(*) AS orders,
       coalesce(sum(subtotal), 0) AS sales,
       coalesce(sum(discount_amount), 0) AS discounts,
       coalesce(sum(platform_commission), 0) AS commission,
       coalesce(sum(flat_usage_fee), 0) AS client_fees
FROM orders
WHERE restaurant_id = :rid
  AND status = 'delivered'
  AND COALESCE(delivered_at, placed_at) >= :since
"""


async def maybe_send_weekly_business_summary() -> None:
    async with async_session() as db:
        now = await local_now(db)
        if now.weekday() != SUMMARY_WEEKDAY or now.hour < SUMMARY_HOUR:
            return
        today = now.date().isoformat()
        last = (await get_setting_value(db, "BUSINESS_SUMMARY_LAST_DATE", "")).strip()
        if last == today:
            return

        since = now - timedelta(days=7)
        base = (await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)).rstrip("/")
        businesses = (
            await db.execute(
                text(
                    """
                    SELECT r.id, r.name, r.slug
                    FROM restaurants r
                    WHERE r.status = 'active'
                      AND r.affiliation_expires_at IS NOT NULL
                      AND r.affiliation_expires_at >= CURRENT_DATE
                    ORDER BY r.name
                    """
                )
            )
        ).mappings().all()

        for business in businesses:
            stats = (
                await db.execute(
                    text(BUSINESS_STATS_SQL),
                    {"rid": business["id"], "since": since},
                )
            ).mappings().one()
            if not stats["orders"]:
                continue

            top = (
                await db.execute(
                    text(
                        """
                        SELECT oi.name, sum(oi.quantity) AS qty, sum(oi.subtotal) AS total
                        FROM order_items oi
                        JOIN orders o ON o.id = oi.order_id
                        WHERE o.restaurant_id = :rid
                          AND o.status = 'delivered'
                          AND COALESCE(o.delivered_at, o.placed_at) >= :since
                        GROUP BY oi.name
                        ORDER BY qty DESC
                        LIMIT 5
                        """
                    ),
                    {"rid": business["id"], "since": since},
                )
            ).mappings().all()

            emails = set()
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT DISTINCT u.email
                        FROM users u
                        JOIN restaurant_users ru ON ru.user_id = u.id
                        WHERE ru.restaurant_id = :rid
                          AND ru.is_active = true
                          AND ru.role IN ('owner', 'manager')
                          AND u.is_active = true
                          AND u.email IS NOT NULL
                        """
                    ),
                    {"rid": business["id"]},
                )
            ).all()
            for row in rows:
                emails.add(row[0])
            if not emails:
                continue

            net = (
                float(stats["sales"])
                - float(stats["discounts"])
                - float(stats["commission"])
            )
            top_rows = "".join(
                f"<tr><td style='padding:5px 0'>{item['name']}</td>"
                f"<td style='padding:5px 0;text-align:right'>{int(item['qty'])}</td>"
                f"<td style='padding:5px 0;text-align:right'>${float(item['total']):.2f}</td></tr>"
                for item in top
            )
            subject = f"Tu resumen semanal · {business['name']}"
            earnings_path = f"/web/restaurants/{business['id']}/earnings"
            earnings_url = f"{base}{earnings_path}" if base else earnings_path
            logo_url = f"{base}/static/logo.png" if base else "/static/logo.png"
            html = f"""
            <div style="font-family:Arial,sans-serif;background:#f4f7fb;padding:24px">
              <div style="max-width:620px;margin:auto;background:#fff;border-radius:14px;overflow:hidden">
                <div style="background:#0d1b2a;color:#fff;padding:20px 26px">
                  <img src="{logo_url}" alt="TuPedidoJR" style="height:38px;display:block;background:#fff;border-radius:8px;padding:5px 9px">
                  <p style="margin:10px 0 0;opacity:.85;font-size:14px">Resumen semanal de {business['name']}</p>
                </div>
                <div style="padding:26px;color:#243447;line-height:1.55">
                  <p>Estos son tus números de los últimos 7 días:</p>
                  <table style="width:100%;font-size:14px;border-collapse:collapse;margin:16px 0">
                    <tr><td style="padding:6px 0;color:#64748b">Pedidos entregados</td><td style="text-align:right"><strong>{int(stats['orders'])}</strong></td></tr>
                    <tr><td style="padding:6px 0;color:#64748b">Ventas</td><td style="text-align:right"><strong>${float(stats['sales']):.2f}</strong></td></tr>
                    <tr><td style="padding:6px 0;color:#64748b">Descuentos de cupones</td><td style="text-align:right">-${float(stats['discounts']):.2f}</td></tr>
                    <tr><td style="padding:6px 0;color:#64748b">Comisión de la plataforma</td><td style="text-align:right">-${float(stats['commission']):.2f}</td></tr>
                    <tr><td style="padding:8px 0;border-top:1px solid #e3e9f0"><strong>Neto del negocio</strong></td><td style="text-align:right;padding-top:8px;border-top:1px solid #e3e9f0"><strong>${net:.2f}</strong></td></tr>
                    <tr><td style="padding:6px 0;color:#64748b">Cuota del cliente (informativa)</td><td style="text-align:right">${float(stats['client_fees']):.2f}</td></tr>
                  </table>
                  <h3 style="font-size:15px;margin:18px 0 6px">Productos más vendidos</h3>
                  <table style="width:100%;font-size:13px;border-collapse:collapse">
                    <thead><tr><th style="text-align:left;padding:5px 0">Producto</th><th style="text-align:right">Cantidad</th><th style="text-align:right">Total</th></tr></thead>
                    <tbody>{top_rows or '<tr><td style="padding:6px 0;color:#64748b">Sin productos en el periodo.</td></tr>'}</tbody>
                  </table>
                  <p style="margin:24px 0 0">
                    <a href="{earnings_url}" style="background:#1B2F6B;color:#fff;padding:11px 18px;border-radius:8px;text-decoration:none">
                      Ver mis ganancias
                    </a>
                  </p>
                  <p style="margin-top:24px;font-size:12px;color:#6c757d">
                    La cuota del cliente la paga el cliente; no se descuenta de tu neto.
                  </p>
                </div>
              </div>
            </div>
            """
            for email in emails:
                await send_email(db, email, subject, html)

        await set_setting(db, "BUSINESS_SUMMARY_LAST_DATE", today)
        await db.commit()


async def business_summary_loop(interval_seconds: int = 6 * 3600) -> None:
    while True:
        try:
            await maybe_send_weekly_business_summary()
        except Exception:
            logger.exception("No se pudo enviar el resumen semanal de negocios")
        await asyncio.sleep(interval_seconds)
