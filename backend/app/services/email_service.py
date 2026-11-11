"""SMTP email delivery and transactional messages."""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.order_service import get_setting_value

logger = logging.getLogger(__name__)

MANUALS = [
    ("Manual general del restaurante", "/manuales/restaurante"),
    ("Manual de menú, precios y opciones", "/manuales/menu"),
    ("Manual de pedidos, cobros y liquidaciones", "/manuales/pedidos"),
]


async def email_config(db: AsyncSession) -> dict:
    return {
        "enabled": (await get_setting_value(db, "EMAIL_ENABLED", "false")).lower() == "true",
        "host": (await get_setting_value(db, "SMTP_HOST", "")).strip(),
        "port": int(await get_setting_value(db, "SMTP_PORT", "587") or 587),
        "username": (await get_setting_value(db, "SMTP_USERNAME", "")).strip(),
        "password": await get_setting_value(db, "SMTP_PASSWORD", ""),
        "use_tls": (await get_setting_value(db, "SMTP_USE_TLS", "true")).lower() == "true",
        "use_ssl": (await get_setting_value(db, "SMTP_USE_SSL", "false")).lower() == "true",
        "from_name": (await get_setting_value(db, "SMTP_FROM_NAME", "TuPedidoJR")).strip(),
        "from_email": (await get_setting_value(db, "SMTP_FROM_EMAIL", "")).strip(),
        "public_url": (
            await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)
        ).rstrip("/"),
    }


async def send_email(
    db: AsyncSession,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> tuple[bool, str]:
    config = await email_config(db)
    if not config["enabled"]:
        return False, "El envío de correos está desactivado"
    if not config["host"] or not config["from_email"]:
        return False, "Falta configurar el servidor SMTP y el correo remitente"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config["from_name"], config["from_email"]))
    message["To"] = to
    message.set_content(text or "Abre este correo en un cliente compatible con HTML.")
    message.add_alternative(html, subtype="html")
    for filename, content, mime in attachments or []:
        maintype, subtype = mime.split("/", 1)
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    def _send():
        if config["use_ssl"]:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(config["host"], config["port"], context=context, timeout=20)
        else:
            server = smtplib.SMTP(config["host"], config["port"], timeout=20)
        try:
            server.ehlo()
            if config["use_tls"] and not config["use_ssl"]:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if config["username"]:
                server.login(config["username"], config["password"])
            server.send_message(message)
        finally:
            try:
                server.quit()
            except Exception:
                pass

    try:
        await asyncio.to_thread(_send)
        return True, "Correo enviado"
    except Exception as exc:
        logger.warning("No se pudo enviar correo a %s: %s", to, exc)
        return False, str(exc)


def _email_shell(title: str, intro: str, body: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;background:#f4f7fb;padding:24px">
      <div style="max-width:620px;margin:auto;background:#fff;border-radius:14px;overflow:hidden">
        <div style="background:#0d1b2a;color:#fff;padding:22px 26px">
          <h1 style="margin:0;font-size:22px">TuPedidoJR</h1>
          <p style="margin:6px 0 0;opacity:.8">{title}</p>
        </div>
        <div style="padding:26px;color:#243447;line-height:1.55">
          <p>{intro}</p>
          {body}
          <p style="margin-top:28px;font-size:12px;color:#6c757d">
            Este correo fue enviado automáticamente por TuPedidoJR.
          </p>
        </div>
      </div>
    </div>
    """


def manuals_html(public_url: str) -> str:
    links = "".join(
        f'<li style="margin-bottom:8px"><a href="{public_url}{path}" '
        f'style="color:#0d6efd">{label}</a></li>'
        for label, path in MANUALS
    )
    return f"""
      <div style="background:#eef4ff;border-radius:10px;padding:16px 18px;margin:18px 0">
        <strong>Manuales de usuario</strong>
        <ul style="margin:10px 0 0;padding-left:20px">{links}</ul>
        <p style="font-size:12px;color:#555;margin-bottom:0">
          Puedes abrirlos en el navegador e imprimirlos o guardarlos como PDF.
        </p>
      </div>
    """


async def send_restaurant_welcome(
    db: AsyncSession,
    to: str,
    owner_name: str,
    restaurant_name: str,
    pending: bool = True,
) -> tuple[bool, str]:
    config = await email_config(db)
    public_url = config["public_url"]
    if pending:
        title = "Bienvenido a TuPedidoJR"
        intro = f"Hola {owner_name}, recibimos la solicitud para registrar <strong>{restaurant_name}</strong>."
        body = """
          <p>Nuestro equipo revisará la información. Cuando el restaurante sea aprobado podrás
          iniciar sesión y comenzar a recibir pedidos.</p>
        """
    else:
        title = "Tu restaurante ya está activo"
        intro = f"Hola {owner_name}, <strong>{restaurant_name}</strong> ya fue aprobado en TuPedidoJR."
        body = f"""
          <p>Ya puedes iniciar sesión en el panel del restaurante:</p>
          <p><a href="{public_url}/web/login" style="color:#0d6efd">{public_url}/web/login</a></p>
          <p>Configura tu menú, horarios y datos bancarios antes de abrir.</p>
        """
    html = _email_shell(title, intro, body + manuals_html(public_url))
    return await send_email(db, to, f"{title} — TuPedidoJR", html)


async def send_restaurant_rejected(
    db: AsyncSession,
    to: str,
    owner_name: str,
    restaurant_name: str,
    reason: str | None,
) -> tuple[bool, str]:
    config = await email_config(db)
    html = _email_shell(
        "Solicitud no aprobada",
        f"Hola {owner_name}, revisamos la solicitud de <strong>{restaurant_name}</strong>.",
        f"<p>Por el momento no fue aprobada.</p>"
        f"{f'<p><strong>Motivo:</strong> {reason}</p>' if reason else ''}"
        f"<p>Puedes responder a este correo para solicitar una revisión.</p>",
    )
    return await send_email(db, to, "Solicitud de restaurante — TuPedidoJR", html)


async def send_password_reset(
    db: AsyncSession,
    to: str,
    name: str,
    reset_url: str,
) -> tuple[bool, str]:
    html = _email_shell(
        "Restablece tu contraseña",
        f"Hola {name}, recibimos una solicitud para restablecer tu contraseña.",
        f"""
        <p style="margin:22px 0">
          <a href="{reset_url}" style="background:#0d6efd;color:#fff;padding:12px 20px;
             border-radius:8px;text-decoration:none;font-weight:bold">Crear nueva contraseña</a>
        </p>
        <p>El enlace vence en 24 horas. Si no solicitaste este cambio, ignora este correo.</p>
        """,
    )
    return await send_email(db, to, "Restablece tu contraseña — TuPedidoJR", html)


async def send_team_welcome(
    db: AsyncSession,
    to: str,
    name: str,
    restaurant_name: str,
    role_label: str,
    temporary_password: str,
) -> tuple[bool, str]:
    config = await email_config(db)
    html = _email_shell(
        "Acceso al equipo del restaurante",
        f"Hola {name}, fuiste agregado al equipo de <strong>{restaurant_name}</strong> como {role_label}.",
        f"""
        <p>Ingresa con:</p>
        <ul>
          <li><strong>Correo:</strong> {to}</li>
          <li><strong>Contraseña temporal:</strong> {temporary_password}</li>
        </ul>
        <p><a href="{config['public_url']}/web/login" style="color:#0d6efd">Iniciar sesión</a></p>
        <p>Por seguridad, cambia tu contraseña desde el perfil.</p>
        """ + manuals_html(config["public_url"]),
    )
    return await send_email(db, to, f"Acceso al equipo de {restaurant_name} — TuPedidoJR", html)
