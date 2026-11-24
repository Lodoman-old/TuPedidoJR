"""Aplica transferencias preaprobadas o fallidas a pedidos y clientes."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from html import escape

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.order import Order
from app.models.receipt_validation import ReceiptValidation
from app.models.user import User
from app.services.audit_service import log_action
from app.services.email_service import send_email
from app.services.order_service import get_setting_value
from app.services.push_service import notify_admin_transfer_failed, send_to_user
from app.services.rounding import round_half_down

logger = logging.getLogger(__name__)


async def apply_preapproved_transfer(
    db: AsyncSession,
    record: ReceiptValidation,
    *,
    actor_id=None,
) -> None:
    """Marca el pedido como pagado con la preaprobación de Gemini."""
    order = await db.get(Order, record.entity_id)
    if not order or order.payment_status == "approved":
        return

    extracted = record.extracted or {}
    order.cep_status = "preapproved"
    order.payment_status = "approved"
    order.cep_payload = {
        **(order.cep_payload or {}),
        "preapproved": True,
        "reason": extracted.get("_fallback_reason"),
        "same_bank": bool(extracted.get("_same_bank")),
    }

    from app.services.payout_service import credit_courier_for_order

    await credit_courier_for_order(db, order)
    await log_action(
        db,
        actor_id,
        "transfer.cep_preapproved",
        "order",
        order.id,
        {
            "total": str(order.total),
            "same_bank": bool(extracted.get("_same_bank")),
        },
    )


async def settle_order_transfer(
    db: AsyncSession,
    record: ReceiptValidation,
    approved: bool,
    *,
    actor_id=None,
) -> None:
    """Confirma o rechaza una transferencia y actualiza el pedido."""
    order = await db.get(Order, record.entity_id)
    if not order:
        return

    if not approved:
        if order.payment_status == "approved":
            await charge_failed_transfer(
                db,
                record,
                "El administrador rechazó el comprobante.",
            )
            return
        if order.status != "cancelled":
            order.status = "cancelled"
            order.cancellation_reason = "Pago rechazado por el administrador."
            order.cancelled_at = datetime.now(timezone.utc)
        order.cep_status = "rejected"
        customer = await db.get(User, order.user_id) if order.user_id else None
        await _notify_customer_failed(
            db, customer, order, Decimal("0"), cancelled=True
        )
        return

    if order.cep_status == "valid" and order.payment_status == "approved":
        return

    already_paid = order.payment_status == "approved"
    extracted = record.extracted or {}
    details = (extracted.get("validation") or {}).get("cepDetails") or {}
    key = str(
        extracted.get("trackingKey") or details.get("trackingKey") or ""
    ).strip()
    if key:
        existing = await db.scalar(
            select(Order.id).where(
                Order.transfer_tracking_key == key,
                Order.id != order.id,
            )
        )
        if not existing:
            order.transfer_tracking_key = key

    order.cep_status = "valid"
    order.cep_validated_at = datetime.now(timezone.utc)
    order.cep_sender_bank = (
        extracted.get("senderBank")
        or details.get("senderBank")
        or order.cep_sender_bank
    )
    order.cep_receiver_bank = order.cep_receiver_bank or details.get("receiverBank")
    order.payment_status = "approved"

    if not already_paid:
        from app.services.payout_service import credit_courier_for_order

        await credit_courier_for_order(db, order)

    if actor_id:
        await log_action(
            db,
            actor_id,
            "transfer.cep_approved",
            "order",
            order.id,
            {"total": str(order.total)},
        )


async def charge_failed_transfer(
    db: AsyncSession, record: ReceiptValidation, reason: str
) -> None:
    """Carga al cliente el monto de un pedido cuyo pago no confirmó Banxico."""
    order = await db.get(Order, record.entity_id)
    if not order:
        return

    extracted = dict(record.extracted or {})
    if extracted.get("charged_to_balance") is not None:
        record.status = "failed"
        return

    customer = await db.get(User, order.user_id) if order.user_id else None
    fulfilled = order.status in ("preparing", "ready", "in_delivery", "delivered")

    if not fulfilled:
        if order.status != "cancelled":
            order.status = "cancelled"
            order.cancellation_reason = "Pago no confirmado por Banxico."
            order.cancelled_at = datetime.now(timezone.utc)
        order.cep_status = "failed"
        order.cep_payload = {
            **(order.cep_payload or {}),
            "failed_reason": reason,
            "charged_to_balance": False,
        }
        extracted["charged_to_balance"] = False
        record.status = "failed"
        record.summary = "Pago no confirmado. El pedido se canceló sin cargo."
        record.extracted = extracted
        await db.commit()
        await _notify_customer_failed(db, customer, order, Decimal("0"), cancelled=True)
        await notify_admin_transfer_failed(
            str(order.id),
            order.total,
            customer.name if customer else "Cliente",
            reason,
            charged=False,
        )
        return

    amount = round_half_down(Decimal(order.total or 0))
    charged = bool(customer and amount > 0)
    if charged:
        customer.pending_balance = round_half_down(
            (customer.pending_balance or Decimal("0")) + amount
        )
        extracted["charged_to_balance"] = True
        extracted["charged_amount"] = str(amount)
    else:
        extracted["charged_to_balance"] = False

    order.cep_status = "failed"
    order.cep_payload = {
        **(order.cep_payload or {}),
        "failed_reason": reason,
        "charged_to_balance": charged,
    }
    record.status = "failed"
    record.summary = (
        "Banxico no confirmó el pago. El monto se cargó al saldo del cliente."
        if charged
        else "Banxico no confirmó el pago. No se pudo cargar al cliente."
    )
    record.extracted = extracted
    await log_action(
        db,
        None,
        "transfer.cep_failed",
        "order",
        order.id,
        {"reason": reason, "amount": str(amount), "charged": charged},
    )
    await db.commit()
    await _notify_customer_failed(db, customer, order, amount, cancelled=False)
    await notify_admin_transfer_failed(
        str(order.id),
        amount,
        customer.name if customer else "Cliente",
        reason,
        charged=charged,
    )


async def cancel_unpaid_transfer(
    db: AsyncSession, order: Order, reason: str
) -> None:
    """Cancela un pedido cuya transferencia no se confirmó a tiempo."""
    if order.status != "cancelled":
        order.status = "cancelled"
        order.cancellation_reason = reason
        order.cancelled_at = datetime.now(timezone.utc)
    order.cep_status = "expired"
    await db.commit()
    customer = await db.get(User, order.user_id) if order.user_id else None
    await _notify_customer_failed(db, customer, order, Decimal("0"), cancelled=True)
    await notify_admin_transfer_failed(
        str(order.id),
        order.total,
        customer.name if customer else "Cliente",
        reason,
        charged=False,
    )


async def _notify_customer_failed(
    db: AsyncSession,
    customer: User | None,
    order: Order,
    amount: Decimal,
    *,
    cancelled: bool,
) -> None:
    if not customer:
        return

    short = str(order.id)[:8].upper()
    if cancelled:
        title = "Pedido cancelado"
        message = (
            f"Tu pedido #{short} se canceló porque no se confirmó el pago "
            "por transferencia."
        )
        subject = f"Pedido #{short} cancelado"
    else:
        title = "Transferencia no confirmada"
        message = (
            f"No pudimos confirmar tu transferencia del pedido #{short}. "
            f"El monto de ${amount:,.2f} se agregó a tu saldo pendiente y se "
            "aplicará a tu próximo pedido."
        )
        subject = f"Transferencia no confirmada · Pedido #{short}"

    try:
        await send_to_user(
            db,
            customer.id,
            title,
            message,
            {"type": "transfer_failed", "order_id": str(order.id)},
            "red",
        )
    except Exception:
        logger.exception("No se pudo enviar push de transferencia fallida")

    if not customer.email:
        return

    try:
        public_url = (
            await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)
        ).rstrip("/")
    except Exception:
        public_url = ""
    link = f"{public_url}/web/orders/{order.id}" if public_url else ""

    html = f"""
      <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;background:#fff;border-radius:12px;padding:24px;border:1px solid #e5e7eb">
        <h2 style="margin:0 0 8px;color:#1B2F6B">{escape(title)}</h2>
        <p style="margin:0 0 16px;color:#475569">{escape(message)}</p>
        <p style="margin:0 0 16px;color:#475569">
          Si crees que es un error, contacta a soporte desde la plataforma.
        </p>
        {f'<p style="margin:22px 0 0"><a href="{escape(link)}" style="background:#1B2F6B;color:#fff;padding:11px 18px;border-radius:8px;text-decoration:none">Ver pedido</a></p>' if link else ''}
      </div>
    """
    try:
        await send_email(db, customer.email, subject, html, message)
    except Exception:
        logger.exception("No se pudo enviar correo de transferencia fallida")
