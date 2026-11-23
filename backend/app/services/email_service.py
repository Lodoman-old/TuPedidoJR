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

# Dominios que suelen escribirse mal y que no existen o no son de correo.
COMMON_EMAIL_TYPOS = {
    "oulook.com": "outlook.com",
    "outlok.com": "outlook.com",
    "outlook.con": "outlook.com",
    "hotmal.com": "hotmail.com",
    "hotmai.com": "hotmail.com",
    "hotmail.con": "hotmail.com",
    "gmail.con": "gmail.com",
    "gmail.cm": "gmail.com",
    "yahoo.con": "yahoo.com",
    "yaho.com": "yahoo.com",
    "icloud.con": "icloud.com",
    "protonmai.com": "protonmail.com",
}


def email_typo_suggestion(email: str) -> str | None:
    """Devuelve el correo corregido si el dominio es un error típico."""
    value = (email or "").strip().lower()
    if "@" not in value:
        return None
    local, domain = value.rsplit("@", 1)
    fixed = COMMON_EMAIL_TYPOS.get(domain)
    return f"{local}@{fixed}" if fixed else None


MANUALS = [
    ("Manual general del negocio", "/manuales/restaurante"),
    ("Manual de menú/catálogo y precios", "/manuales/menu"),
    ("Manual de pedidos y cobros", "/manuales/pedidos"),
    ("Manual de envíos de negocio", "/manuales/envios"),
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
    suggestion = email_typo_suggestion(to)
    if suggestion:
        return False, (
            f"El correo {to} parece tener un error de escritura. "
            f"¿Quisiste decir {suggestion}? Corrígelo y vuelve a enviar."
        )

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


def _email_shell(title: str, intro: str, body: str, logo_url: str | None = None) -> str:
    logo = (
        f'<img src="{logo_url}" alt="TuPedidoJR" '
        'style="height:46px;display:block;background:#fff;border-radius:10px;padding:6px 10px">'
        if logo_url else '<h1 style="margin:0;font-size:22px">TuPedidoJR</h1>'
    )
    return f"""
    <div style="font-family:Arial,sans-serif;background:#f4f7fb;padding:24px">
      <div style="max-width:620px;margin:auto;background:#fff;border-radius:14px;overflow:hidden">
        <div style="background:#0d1b2a;color:#fff;padding:20px 26px">
          {logo}
          <p style="margin:12px 0 0;opacity:.85;font-size:14px">{title}</p>
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


def manuals_html(public_url: str, role: str = "business") -> str:
    items = (
        [("Manual del repartidor", "/manuales/repartidor")]
        if role == "courier"
        else MANUALS
    )
    items = items + [("Todos los manuales", "/manuales")]
    links = "".join(
        f'<li style="margin-bottom:8px"><a href="{public_url}{path}" '
        f'style="color:#0d6efd">{label}</a></li>'
        for label, path in items
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
          <p>Nuestro equipo revisará la información. Cuando el negocio sea aprobado podrás
          iniciar sesión y comenzar a recibir pedidos.</p>
        """
    else:
        title = "Tu negocio ya está activo"
        intro = f"Hola {owner_name}, <strong>{restaurant_name}</strong> ya fue aprobado en TuPedidoJR."
        body = f"""
          <p>Ya puedes iniciar sesión en el panel del negocio:</p>
          <p><a href="{public_url}/web/login" style="color:#0d6efd">{public_url}/web/login</a></p>
          <p>Configura tu menú o catálogo, horarios y datos bancarios antes de abrir.</p>
        """
    html = _email_shell(
        title, intro, body + manuals_html(public_url),
        logo_url=f"{public_url}/static/logo.png",
    )
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
        logo_url=f"{config['public_url']}/static/logo.png",
    )
    return await send_email(db, to, "Solicitud de negocio — TuPedidoJR", html)


async def send_password_reset(
    db: AsyncSession,
    to: str,
    name: str,
    reset_url: str,
) -> tuple[bool, str]:
    config = await email_config(db)
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
        logo_url=f"{config['public_url']}/static/logo.png",
    )
    return await send_email(db, to, "Restablece tu contraseña — TuPedidoJR", html)


async def send_email_verification(
    db: AsyncSession,
    to: str,
    name: str,
    verify_url: str,
) -> tuple[bool, str]:
    config = await email_config(db)
    html = _email_shell(
        "Confirma tu correo",
        f"Hola {name}, confirma tu correo para activar todas las funciones de TuPedidoJR.",
        f"""
        <p style="margin:22px 0">
          <a href="{verify_url}" style="background:#0d6efd;color:#fff;padding:12px 20px;
             border-radius:8px;text-decoration:none;font-weight:bold">Confirmar mi correo</a>
        </p>
        <p>El enlace vence en 3 días. Si no creaste esta cuenta, ignora este correo.</p>
        """,
        logo_url=f"{config['public_url']}/static/logo.png",
    )
    return await send_email(db, to, "Confirma tu correo — TuPedidoJR", html)


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
        "Acceso al equipo del negocio",
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
        logo_url=f"{config['public_url']}/static/logo.png",
    )
    return await send_email(db, to, f"Acceso al equipo de {restaurant_name} — TuPedidoJR", html)


async def send_courier_welcome(
    db: AsyncSession,
    to: str,
    name: str,
) -> tuple[bool, str]:
    config = await email_config(db)
    public_url = config["public_url"]
    html = _email_shell(
        "Bienvenido a TuPedidoJR",
        f"Hola {name}, ya tienes acceso como repartidor.",
        f"""
        <p>Entra al panel del repartidor con tu correo y contraseña:</p>
        <p><a href="{public_url}/web/login" style="color:#0d6efd">{public_url}/web/login</a></p>
        <p>Antes de empezar, revisa tu manual: disponibilidad, contadores, límite de
        servicios, incidencias y corte de cuentas.</p>
        """ + manuals_html(public_url, "courier"),
        logo_url=f"{public_url}/static/logo.png",
    )
    return await send_email(
        db, to, "Bienvenido a TuPedidoJR — Manual del repartidor", html
    )
