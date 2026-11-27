"""Registro de accesos al sistema: IP, usuario y pantalla.

Las visitas se guardan para que el administrador pueda ver desde qué IPs se
entra y qué pantallas se usan. No se guardan contraseñas ni datos del negocio.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access_log import AccessLog
from app.models.delivery_person import DeliveryPerson
from app.models.restaurant_user import RestaurantUser
from app.models.user import User

logger = logging.getLogger(__name__)

# Pantallas conocidas. Se usa la coincidencia más larga.
SCREEN_LABELS: dict[str, str] = {
    "/web/login": "Inicio de sesión",
    "/web/register": "Registro",
    "/web/forgot-password": "Recuperar contraseña",
    "/web/reset-password": "Restablecer contraseña",
    "/web/verify-email": "Verificar correo",
    "/web/verify-phone": "Verificar teléfono",
    "/web/inicio": "Inicio",
    "/web/restaurants": "Negocios",
    "/web/cart": "Carrito",
    "/web/orders": "Mis pedidos",
    "/web/balance": "Saldo pendiente",
    "/web/profile": "Mi perfil",
    "/web/delivery": "Panel del repartidor",
    "/web/mandados": "Mandados",
    "/web/shipments": "Envíos",
    "/web/recargas": "Recargas",
    "/web/my-rentals": "Mis rentas",
    "/web/reservations": "Reservaciones",
    "/web/my-appointments": "Mis citas",
    "/web/store-requests": "Solicitudes de tienda",
    "/web/app": "Descargar app",
    "/web/admin/dashboard": "Admin · Inicio",
    "/web/admin/orders": "Admin · Pedidos",
    "/web/admin/restaurants": "Admin · Negocios",
    "/web/admin/couriers": "Admin · Repartidores",
    "/web/admin/recargas": "Admin · Recargas",
    "/web/admin/users": "Admin · Usuarios",
    "/web/admin/online": "Admin · Usuarios en línea",
    "/web/admin/payouts": "Admin · Pagos y cobros",
    "/web/admin/incidents": "Admin · Incidencias",
    "/web/admin/receipts": "Admin · Comprobantes",
    "/web/admin/transfers": "Admin · Transferencias",
    "/web/admin/agenda": "Admin · Agenda y saldos",
    "/web/admin/reports": "Admin · Reportes",
    "/web/admin/settings": "Admin · Configuración",
    "/web/admin/push": "Admin · Notificaciones",
    "/web/admin/audit": "Admin · Auditoría",
    "/web/admin/security": "Admin · Seguridad",
    "/web/admin/access": "Admin · Accesos e IPs",
}

# Rutas con identificador: se agrupan con su pantalla base.
SCREEN_PREFIXES: tuple[tuple[str, str], ...] = tuple(
    sorted(SCREEN_LABELS.items(), key=lambda item: len(item[0]), reverse=True)
)


def screen_label(path: str | None) -> str:
    """Devuelve un nombre legible para la ruta visitada."""
    clean = (path or "").split("?", 1)[0].strip().rstrip("/") or "/"
    if clean in SCREEN_LABELS:
        return SCREEN_LABELS[clean]
    for prefix, label in SCREEN_PREFIXES:
        if clean == prefix or clean.startswith(prefix + "/"):
            if prefix.startswith("/web/admin"):
                return label
            if label == "Negocios":
                return "Negocio · " + clean.split("/")[-1]
            return label
    return clean[:120]


async def role_for(db: AsyncSession, user: User) -> str:
    """Clasifica al usuario como admin, repartidor, negocio o cliente."""
    if user.is_superuser:
        return "admin"
    courier = await db.execute(
        select(DeliveryPerson.id).where(DeliveryPerson.user_id == user.id).limit(1)
    )
    if courier.scalar_one_or_none():
        return "courier"
    member = await db.execute(
        select(RestaurantUser.id)
        .where(
            RestaurantUser.user_id == user.id,
            RestaurantUser.is_active.is_(True),
        )
        .limit(1)
    )
    if member.scalar_one_or_none():
        return "business"
    return "customer"


async def record_access(
    db: AsyncSession,
    user: User | None,
    *,
    role: str | None,
    ip: str | None,
    path: str | None,
    user_agent: str | None = None,
) -> None:
    """Guarda una visita. Nunca interrumpe la navegación."""
    try:
        clean_path = (path or "/").split("?", 1)[0].strip()[:300] or "/"
        db.add(
            AccessLog(
                user_id=user.id if user else None,
                ip=(ip or "")[:64] or None,
                role=(role or "")[:20] or None,
                path=clean_path,
                screen=screen_label(clean_path)[:120],
                user_agent=(user_agent or "")[:300] or None,
            )
        )
        await db.commit()
    except Exception:
        logger.exception("No se pudo registrar el acceso")
        try:
            await db.rollback()
        except Exception:
            pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
