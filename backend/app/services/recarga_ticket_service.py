"""Ticket de TuPedidoJR para recargas completadas."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.recarga_order import RecargaOrder
from app.models.user import User
from app.services.email_service import send_email
from app.services.order_service import get_setting_value

TZ = ZoneInfo("America/Mexico_City")

STATUS_LABELS = {
    "requested": "Por pagar",
    "pending": "Pendiente de procesar",
    "processing": "Procesando",
    "completed": "Completada",
    "failed": "Fallida",
    "refunded": "Reembolsada",
    "cancelled": "Cancelada",
}

PAYMENT_LABELS = {
    "cash": "Efectivo",
    "transfer": "Transferencia",
}

ORIGIN_LABELS = {
    "portal": "Portal de recargas",
    "checkout": "Pedido",
    "courier": "Venta del repartidor",
}


def ticket_number(recarga: RecargaOrder) -> str:
    return f"TPJ-R{str(recarga.id)[:8].upper()}"


def _money(value) -> str:
    try:
        return f"${float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _date_label(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ).strftime("%d/%m/%Y %H:%M")


def ticket_payload(recarga: RecargaOrder) -> dict:
    return {
        "id": str(recarga.id),
        "ticket_number": ticket_number(recarga),
        "customer_name": recarga.customer_name or "Cliente",
        "company": recarga.company,
        "phone": recarga.phone,
        "product_description": recarga.product_description
        or recarga.product_code
        or recarga.company,
        "product_code": recarga.product_code,
        "amount": str(recarga.amount or 0),
        "fee": str(recarga.fee or 0),
        "total": str(recarga.total or 0),
        "payment_method": PAYMENT_LABELS.get(
            recarga.payment_method, recarga.payment_method
        ),
        "origin": ORIGIN_LABELS.get(recarga.origin, recarga.origin or ""),
        "status": STATUS_LABELS.get(recarga.status, recarga.status),
        "provider_folio": recarga.provider_folio,
        "order_code": str(recarga.order_id)[:8].upper()
        if recarga.order_id
        else None,
        "created_at": _date_label(recarga.created_at),
        "completed_at": _date_label(recarga.completed_at),
    }


def _ticket_rows(payload: dict) -> list[tuple[str, str]]:
    rows = [
        ("Compañía", payload["company"]),
        ("Teléfono", payload["phone"]),
        ("Producto", payload["product_description"]),
        ("Monto de la recarga", _money(payload["amount"])),
    ]
    if float(payload["fee"] or 0) > 0:
        rows.append(("Comisión", _money(payload["fee"])))
    rows.extend([
        ("Total", _money(payload["total"])),
        ("Forma de pago", payload["payment_method"]),
    ])
    if payload.get("order_code"):
        rows.append(("Pedido", f"#{payload['order_code']}"))
    rows.append(("Folio del proveedor", payload.get("provider_folio") or "—"))
    rows.append(("Fecha", payload["completed_at"]))
    return rows


def build_ticket_html(payload: dict, public_url: str) -> tuple[str, str]:
    logo = f"{public_url.rstrip('/')}/static/logo.png"
    ticket_url = f"{public_url.rstrip('/')}/web/recargas/{payload['id']}/ticket"
    rows_html = "".join(
        f"""
        <tr>
          <td style="padding:8px 0;color:#64748b;font-size:13px">{escape(label)}</td>
          <td style="padding:8px 0;text-align:right;font-weight:600;color:#0f172a">{escape(str(value))}</td>
        </tr>"""
        for label, value in _ticket_rows(payload)
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;background:#fff;
                border:1px solid #e2e8f0;border-radius:14px;overflow:hidden">
      <div style="background:#1B2F6B;padding:22px 24px;color:#fff">
        <img src="{escape(logo)}" alt="TuPedidoJR" style="height:42px;background:#fff;border-radius:8px;padding:5px 8px">
        <div style="font-size:20px;font-weight:700;margin-top:14px">Ticket de recarga</div>
        <div style="font-size:13px;opacity:.85">{escape(payload['ticket_number'])}</div>
      </div>
      <div style="padding:24px">
        <div style="font-size:14px;color:#334155;margin-bottom:16px">
          Hola {escape(payload['customer_name'])}. Tu recarga quedó <strong>{escape(payload['status'])}</strong>.
        </div>
        <table style="width:100%;border-collapse:collapse;border-top:1px solid #e2e8f0">
          {rows_html}
        </table>
        <div style="margin-top:18px;padding:14px;background:#f8fafc;border-radius:10px;
                    font-size:13px;color:#475569">
          <strong>Total cobrado:</strong> {escape(_money(payload['total']))}<br>
          Este ticket es tu comprobante de TuPedidoJR. Conserva el folio del proveedor para cualquier aclaración.
        </div>
        <div style="margin-top:20px;text-align:center">
          <a href="{escape(ticket_url)}"
             style="display:inline-block;background:#1B2F6B;color:#fff;padding:10px 18px;
                    border-radius:8px;text-decoration:none;font-weight:600;font-size:13px">
            Ver ticket en línea
          </a>
        </div>
      </div>
      <div style="padding:14px 24px;background:#f1f5f9;color:#64748b;font-size:11px;text-align:center">
        TuPedidoJR · tupedidojr.com
      </div>
    </div>
    """
    text_rows = "\n".join(
        f"{label}: {value}" for label, value in _ticket_rows(payload)
    )
    text = (
        f"Ticket de recarga TuPedidoJR {payload['ticket_number']}\n\n"
        f"{text_rows}\n\n"
        f"Total cobrado: {_money(payload['total'])}\n"
        f"Ver ticket: {ticket_url}\n"
    )
    return html, text


async def send_recarga_ticket(
    db: AsyncSession, recarga: RecargaOrder, *, force: bool = False
) -> bool:
    """Envía al cliente el ticket de una recarga completada."""
    if recarga.status != "completed":
        return False
    if recarga.ticket_sent_at is not None and not force:
        return False
    if not recarga.user_id:
        return False
    user = await db.get(User, recarga.user_id)
    if user is None or not user.email:
        return False
    public_url = (
        await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)
    ).rstrip("/")
    payload = ticket_payload(recarga)
    html, text = build_ticket_html(payload, public_url)
    subject = (
        f"Ticket TuPedidoJR · {recarga.company} "
        f"{_money(recarga.amount)} · {recarga.phone}"
    )
    sent, detail = await send_email(db, user.email, subject, html, text)
    if not sent:
        return False
    recarga.ticket_sent_at = datetime.now(timezone.utc)
    await db.commit()
    return True
