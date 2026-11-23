"""Correo con el QR imprimible cuando se registra el pago de afiliación."""
from __future__ import annotations

import io
import logging
from datetime import date
from html import escape

import segno
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.email_service import send_email

logger = logging.getLogger(__name__)


def restaurant_public_url(restaurant: Restaurant) -> str:
    slug = restaurant.slug or str(restaurant.id)
    return f"{settings.APP_URL.rstrip('/')}/r/{slug}"


def build_qr_png(public_url: str, scale: int = 16) -> bytes:
    qr = segno.make(public_url, error="q")
    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="png",
        scale=scale,
        border=4,
        dark="#000000",
        light="#ffffff",
    )
    return buffer.getvalue()


def _date_label(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


async def send_affiliation_qr_email(
    db: AsyncSession, restaurant: Restaurant
) -> tuple[bool, str]:
    """Envía al dueño su QR listo para imprimir. Devuelve (enviado, detalle)."""
    try:
        return await _send_affiliation_qr_email(db, restaurant)
    except Exception as exc:  # nunca debe tumbar el registro del pago
        logger.exception("No se pudo enviar el QR de afiliación")
        return False, str(exc)


async def _send_affiliation_qr_email(
    db: AsyncSession, restaurant: Restaurant
) -> tuple[bool, str]:
    owner = await db.get(User, restaurant.owner_id)
    if not owner or not owner.email:
        return False, "El negocio no tiene correo de dueño"

    base = settings.APP_URL.rstrip("/")
    public_url = restaurant_public_url(restaurant)
    print_url = f"{base}/web/restaurants/{restaurant.id}/qr?print=1"
    panel_url = f"{base}/web/restaurants/{restaurant.id}/profile"
    logo_url = f"{base}/static/logo.png"
    name = escape(restaurant.name)
    owner_name = escape(owner.name or "equipo")
    expires = _date_label(restaurant.affiliation_expires_at)

    subject = f"Tu QR de TuPedidoJR está listo · {restaurant.name}"
    text = (
        f"Hola {owner.name or 'equipo'},\n\n"
        f"Tu pago de afiliación de {restaurant.name} quedó registrado. "
        f"Tu negocio está activo hasta el {expires}.\n\n"
        f"Adjuntamos tu QR listo para imprimir. También puedes abrirlo en:\n"
        f"{print_url}\n\n"
        f"Tu página pública es:\n{public_url}\n\n"
        "Imprímelo y colócalo en tu mostrador, mesas o volantes. "
        "El cliente escanea y pide desde su celular.\n\n"
        "TuPedidoJR"
    )
    html = f"""
      <div style="font-family:Arial,sans-serif;background:#f4f7fb;padding:24px">
        <div style="max-width:620px;margin:auto;background:#fff;border-radius:14px;overflow:hidden">
          <div style="background:#0d1b2a;color:#fff;padding:22px 26px">
            <img src="{logo_url}" alt="TuPedidoJR" style="height:38px;display:block;background:#fff;border-radius:8px;padding:5px 9px">
            <p style="margin:10px 0 0;opacity:.85;font-size:14px">Tu QR está listo</p>
          </div>
          <div style="padding:26px;color:#243447;line-height:1.55">
            <p>Hola <strong>{owner_name}</strong>,</p>
            <p>
              Tu pago de afiliación de <strong>{name}</strong> quedó registrado.
              Tu negocio está activo hasta el <strong>{expires}</strong>.
            </p>
            <p>
              Adjuntamos tu <strong>QR listo para imprimir</strong>. También puedes
              abrirlo, imprimirlo o guardarlo como PDF desde tu panel.
            </p>
            <div style="background:#eef4ff;border-radius:10px;padding:16px 18px;margin:18px 0">
              <p style="margin:0 0 6px"><strong>Tu página pública</strong></p>
              <p style="margin:0;word-break:break-all"><a href="{public_url}" style="color:#0d6efd">{public_url}</a></p>
            </div>
            <p style="margin:24px 0 10px">
              <a href="{print_url}" style="background:#1B2F6B;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">
                Abrir mi QR para imprimir
              </a>
            </p>
            <p style="margin:0 0 10px">
              <a href="{panel_url}" style="color:#0d6efd">Entrar a mi panel</a>
            </p>
            <p style="margin-top:24px;font-size:13px;color:#5d6b7a">
              Imprímelo y colócalo en tu mostrador, mesas o volantes.
              El cliente escanea y pide desde su celular.
            </p>
            <p style="margin-top:28px;font-size:12px;color:#6c757d">
              Este correo fue enviado automáticamente por TuPedidoJR.
            </p>
          </div>
        </div>
      </div>
    """

    filename = f"qr-{restaurant.slug or restaurant.id}.png"
    return await send_email(
        db,
        owner.email,
        subject,
        html,
        text,
        attachments=[(filename, build_qr_png(public_url), "image/png")],
    )
