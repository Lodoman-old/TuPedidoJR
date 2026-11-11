"""Friendly business settings API for the superuser panel.

The generic key/value table still exists (and is editable in sqladmin), but
this endpoint exposes curated, validated settings so the operator does not
have to remember internal key names.
"""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.setting import Setting
from app.models.user import User
from app.services.audit_service import log_action

router = APIRouter()

# key -> (group, label, description, type, default, options)
KNOWN_SETTINGS: dict[str, dict] = {
    "APP_COMMISSION_PERCENTAGE": {
        "group": "Comisiones", "label": "Comisión de la plataforma",
        "description": "Porcentaje que absorbe el restaurante de cada pedido.",
        "type": "percent", "default": "15.0",
    },
    "APP_FLAT_USAGE_FEE": {
        "group": "Comisiones", "label": "Cuota fija por pedido",
        "description": "Cuota fija que paga el cliente por usar la plataforma.",
        "type": "money", "default": "5.0",
    },
    "DELIVERY_BASE_FEE": {
        "group": "Envíos", "label": "Tarifa base de envío",
        "description": "Costo de envío para distancias dentro del radio incluido.",
        "type": "money", "default": "20.0",
    },
    "DELIVERY_FREE_RADIUS_KM": {
        "group": "Envíos", "label": "Radio incluido (km)",
        "description": "Kilómetros cubiertos por la tarifa base.",
        "type": "float", "default": "6",
    },
    "DELIVERY_EXTRA_FEE_PER_KM": {
        "group": "Envíos", "label": "Costo por km adicional",
        "description": "Cargo extra por cada kilómetro arriba del radio incluido.",
        "type": "money", "default": "5.0",
    },
    "MANDADO_ACTIVE": {
        "group": "Mandados", "label": "Permitir mandados",
        "description": "Activa o desactiva el servicio de mandados.",
        "type": "bool", "default": "true",
    },
    "MANDADO_PLATFORM_FEE": {
        "group": "Mandados", "label": "Comisión por mandado",
        "description": "Ganancia fija de la plataforma por cada mandado.",
        "type": "money", "default": "10.0",
    },
    "MANDADO_RISK_FEE_TYPE": {
        "group": "Mandados", "label": "Tipo de extra por riesgo",
        "description": "Solo se aplica el método seleccionado. El otro valor se ignora.",
        "type": "select", "default": "percentage",
        "options": [
            {"value": "percentage", "label": "Porcentaje"},
            {"value": "fixed", "label": "Monto fijo"},
        ],
    },
    "MANDADO_RISK_PERCENTAGE": {
        "group": "Mandados", "label": "Riesgo (%)",
        "description": "Se usa únicamente cuando el tipo es porcentaje.",
        "type": "percent", "default": "10.0",
    },
    "MANDADO_RISK_FIXED_AMOUNT": {
        "group": "Mandados", "label": "Riesgo (monto fijo)",
        "description": "Se usa únicamente cuando el tipo es monto fijo.",
        "type": "money", "default": "15.0",
    },
    "CANCELLATION_WINDOW_MIN": {
        "group": "Cancelaciones", "label": "Minutos de gracia",
        "description": "Tiempo que tiene el cliente para cancelar después de que el restaurante confirma.",
        "type": "int", "default": "5",
    },
    "CANCELLATION_REFUND_ENABLED": {
        "group": "Cancelaciones", "label": "Generar reembolsos",
        "description": "Marca como reembolso pendiente los pedidos pagados que se cancelan.",
        "type": "bool", "default": "true",
    },
    "RESTAURANT_TIMEZONE": {
        "group": "Horarios", "label": "Zona horaria",
        "description": "Zona horaria usada para los horarios de los restaurantes.",
        "type": "text", "default": "America/Mexico_City",
    },
    "MP_ENABLED": {
        "group": "Pagos", "label": "Mercado Pago",
        "description": "Habilitar pagos en línea con Mercado Pago.",
        "type": "bool", "default": "false",
    },
    "TRANSFER_ENABLED": {
        "group": "Pagos", "label": "Transferencia bancaria",
        "description": "Habilitar pagos por transferencia.",
        "type": "bool", "default": "true",
    },
    "BANK_NAME": {
        "group": "Pagos", "label": "Banco de la plataforma",
        "description": "El cliente transfiere a TuPedidoJR, no al restaurante.",
        "type": "text", "default": "",
    },
    "BANK_ACCOUNT_HOLDER": {
        "group": "Pagos", "label": "Titular de la cuenta de la plataforma",
        "description": "Nombre que verá el cliente al transferir.",
        "type": "text", "default": "",
    },
    "BANK_CLABE": {
        "group": "Pagos", "label": "CLABE de la plataforma",
        "description": "CLABE de 18 dígitos donde TuPedidoJR recibe las transferencias.",
        "type": "text", "default": "",
    },
    "BANK_CARD": {
        "group": "Pagos", "label": "Tarjeta de la plataforma (opcional)",
        "description": "Dato adicional para transferencias o depósitos.",
        "type": "text", "default": "",
    },
    "WHATSAPP_SUPPORT": {
        "group": "Soporte", "label": "WhatsApp de soporte",
        "description": "Número con lada país, sin espacios. Ej. 524121234567.",
        "type": "text", "default": "",
    },
    "PEAK_BONUS_ENABLED": {
        "group": "Repartidores", "label": "Bono por hora pico",
        "description": "Activa un pago extra por entrega durante una franja horaria.",
        "type": "bool", "default": "false",
    },
    "PEAK_BONUS_START": {
        "group": "Repartidores", "label": "Inicio de hora pico",
        "description": "Formato HH:MM. Ej. 13:00.",
        "type": "text", "default": "13:00",
    },
    "PEAK_BONUS_END": {
        "group": "Repartidores", "label": "Fin de hora pico",
        "description": "Formato HH:MM. Ej. 15:00.",
        "type": "text", "default": "15:00",
    },
    "PEAK_BONUS_AMOUNT": {
        "group": "Repartidores", "label": "Monto del bono",
        "description": "Se suma a la ganancia del repartidor por cada entrega en esa franja.",
        "type": "money", "default": "5.0",
    },
    "LOYALTY_ENABLED": {
        "group": "Lealtad", "label": "Programa de puntos",
        "description": "Activa los puntos por compra y los referidos.",
        "type": "bool", "default": "true",
    },
    "LOYALTY_VISIBLE": {
        "group": "Lealtad", "label": "Mostrar puntos a los clientes",
        "description": "Si lo desactivas, se ocultan los puntos y referidos en la web y la app.",
        "type": "bool", "default": "true",
    },
    "LOYALTY_POINTS_PER_100": {
        "group": "Lealtad", "label": "Puntos por cada $100",
        "description": "Puntos que gana el cliente por cada $100 de compra.",
        "type": "float", "default": "5",
    },
    "LOYALTY_VALUE_PER_POINT": {
        "group": "Lealtad", "label": "Valor de cada punto",
        "description": "Pesos que descuenta cada punto al canjearlo.",
        "type": "money", "default": "0.1",
    },
    "REFERRAL_BONUS_POINTS": {
        "group": "Lealtad", "label": "Bono por referido",
        "description": "Puntos para el cliente y para quien lo invitó.",
        "type": "int", "default": "50",
    },
    "EMAIL_ENABLED": {
        "group": "Correos", "label": "Activar correos del sistema",
        "description": "Envía bienvenidas, manuales y recuperación de contraseña.",
        "type": "bool", "default": "false",
    },
    "SMTP_HOST": {
        "group": "Correos", "label": "Servidor SMTP",
        "description": "Ej. smtp.gmail.com, smtp.resend.com o smtp.sendgrid.net.",
        "type": "text", "default": "",
    },
    "SMTP_PORT": {
        "group": "Correos", "label": "Puerto SMTP",
        "description": "Normalmente 587 con STARTTLS o 465 con SSL.",
        "type": "int", "default": "587",
    },
    "SMTP_USERNAME": {
        "group": "Correos", "label": "Usuario SMTP",
        "description": "Usuario o API key del proveedor de correo.",
        "type": "text", "default": "",
    },
    "SMTP_PASSWORD": {
        "group": "Correos", "label": "Contraseña o API key SMTP",
        "description": "Se guarda en la configuración del sistema.",
        "type": "password", "default": "",
    },
    "SMTP_USE_TLS": {
        "group": "Correos", "label": "Usar STARTTLS",
        "description": "Actívalo normalmente con el puerto 587.",
        "type": "bool", "default": "true",
    },
    "SMTP_USE_SSL": {
        "group": "Correos", "label": "Usar SSL directo",
        "description": "Actívalo con el puerto 465; desactiva STARTTLS.",
        "type": "bool", "default": "false",
    },
    "SMTP_FROM_NAME": {
        "group": "Correos", "label": "Nombre del remitente",
        "description": "Nombre que verá el destinatario.",
        "type": "text", "default": "TuPedidoJR",
    },
    "SMTP_FROM_EMAIL": {
        "group": "Correos", "label": "Correo remitente",
        "description": "Debe estar autorizado por el proveedor SMTP.",
        "type": "text", "default": "",
    },
    "APP_PUBLIC_URL": {
        "group": "Correos", "label": "URL pública de la plataforma",
        "description": "Se usa en enlaces de correos y manuales.",
        "type": "text", "default": "http://localhost:8080",
    },
}


class SettingValue(BaseModel):
    key: str
    value: str | None


class SettingsUpdate(BaseModel):
    values: dict[str, str | bool | int | float]


def _normalize_value(key: str, raw) -> str:
    meta = KNOWN_SETTINGS[key]
    kind = meta["type"]

    if kind == "bool":
        if isinstance(raw, bool):
            return "true" if raw else "false"
        text = str(raw).strip().lower()
        if text in ("1", "true", "si", "sí", "yes", "on"):
            return "true"
        if text in ("0", "false", "no", "off"):
            return "false"
        raise HTTPException(status_code=400, detail=f"{meta['label']}: valor booleano inválido")

    if kind in ("percent", "money", "float"):
        try:
            number = Decimal(str(raw).strip())
        except (InvalidOperation, AttributeError):
            raise HTTPException(status_code=400, detail=f"{meta['label']}: número inválido")
        if number < 0:
            raise HTTPException(status_code=400, detail=f"{meta['label']}: no puede ser negativo")
        if kind == "percent" and number > 100:
            raise HTTPException(status_code=400, detail=f"{meta['label']}: máximo 100")
        return f"{number}"

    if kind == "int":
        try:
            number = int(str(raw).strip())
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{meta['label']}: entero inválido")
        if number < 0:
            raise HTTPException(status_code=400, detail=f"{meta['label']}: no puede ser negativo")
        return str(number)

    if kind == "select":
        value = str(raw).strip()
        allowed = {option["value"] for option in meta.get("options", [])}
        if value not in allowed:
            raise HTTPException(status_code=400, detail=f"{meta['label']}: opción inválida")
        return value

    value = str(raw).strip()
    if key == "BANK_CLABE" and value:
        if not value.isdigit() or len(value) != 18:
            raise HTTPException(
                status_code=400,
                detail="CLABE interbancaria: deben ser 18 dígitos",
            )
    return value


@router.get("/public")
async def public_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting).where(Setting.key == "WHATSAPP_SUPPORT"))
    row = result.scalar_one_or_none()
    return {"whatsapp_support": (row.value if row else "") or ""}


@router.get("")
async def list_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(select(Setting))
    stored = {row.key: row.value for row in result.scalars().all()}

    groups: dict[str, list[dict]] = {}
    for key, meta in KNOWN_SETTINGS.items():
        item = {
            "key": key,
            "label": meta["label"],
            "description": meta["description"],
            "type": meta["type"],
            "value": stored.get(key, meta["default"]),
            "default": meta["default"],
        }
        if meta.get("options"):
            item["options"] = meta["options"]
        groups.setdefault(meta["group"], []).append(item)

    return {
        "groups": [
            {"name": name, "settings": items}
            for name, items in groups.items()
        ]
    }


@router.patch("")
async def update_settings(
    body: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    unknown = [key for key in body.values if key not in KNOWN_SETTINGS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Configuración desconocida: {', '.join(unknown)}",
        )

    result = await db.execute(select(Setting))
    existing = {row.key: row for row in result.scalars().all()}

    updated = {}
    for key, raw in body.values.items():
        value = _normalize_value(key, raw)
        setting = existing.get(key)
        if setting:
            setting.value = value
        else:
            db.add(Setting(
                key=key,
                value=value,
                description=KNOWN_SETTINGS[key]["description"],
            ))
        updated[key] = value

    await log_action(
        db, current_user.id, "settings.update", "settings", None,
        {"values": updated},
    )
    await db.commit()
    return {"updated": updated}
