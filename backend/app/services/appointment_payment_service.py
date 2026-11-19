"""Cálculo de pagos de citas y validación de comprobantes."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.db.session import async_session
from app.models.appointment import Appointment
from app.services.receipt_validation_service import TRANSFER, create_and_validate

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")


def _q(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def payment_plan(
    price,
    payment_mode: str,
    client_fee,
    business_fee,
    deposit_percent,
) -> dict:
    """Calcula montos de una cita según la forma de pago.

    - cash: todo en el negocio; el negocio queda debiendo la comisión.
    - deposit: anticipo en línea; el resto en efectivo en el negocio.
    - full: servicio completo en línea; la plataforma liquida al negocio.
    """
    price = _q(price)
    client_fee = _q(client_fee)
    business_fee = _q(business_fee)
    platform_fee = client_fee + business_fee

    if payment_mode == "cash":
        return {
            "online_amount": _q(0),
            "cash_due": _q(price + client_fee),
            "deposit_amount": _q(0),
            "deposit_percent": _q(0),
            "business_credit": _q(0),
            "business_debt": _q(platform_fee),
            "payment_status": "cash_pending",
        }

    if payment_mode == "deposit":
        percent = Decimal(str(deposit_percent or 20))
        percent = min(max(percent, Decimal("10")), Decimal("100"))
        deposit = _q(price * percent / 100)
        if deposit > price:
            deposit = price
        credit = _q(deposit - business_fee)
        debt = _q(business_fee - deposit)
        return {
            "online_amount": _q(deposit + client_fee),
            "cash_due": _q(price - deposit),
            "deposit_amount": deposit,
            "deposit_percent": percent,
            "business_credit": max(credit, Decimal("0")),
            "business_debt": max(debt, Decimal("0")),
            "payment_status": "proof_pending",
        }

    # Pago completo por transferencia.
    credit = _q(price - business_fee)
    debt = _q(business_fee - price)
    return {
        "online_amount": _q(price + client_fee),
        "cash_due": _q(0),
        "deposit_amount": _q(0),
        "deposit_percent": _q(0),
        "business_credit": max(credit, Decimal("0")),
        "business_debt": max(debt, Decimal("0")),
        "payment_status": "proof_pending",
    }


def _reference(record) -> str | None:
    extracted = record.extracted or {}
    value = extracted.get("reference") or extracted.get("account")
    return str(value)[:120] if value else None


async def _run_validation(appointment_id: str) -> None:
    async with async_session() as db:
        appointment = await db.get(Appointment, appointment_id)
        if not appointment or not appointment.proof_url:
            return
        try:
            record = await create_and_validate(
                db,
                "appointment_payment",
                appointment.id,
                appointment.proof_url,
                TRANSFER,
                appointment.online_amount,
                datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("No se pudo validar el comprobante de la cita %s", appointment_id)
            record = None

        if record is not None:
            appointment.payment_reference = _reference(record)
            appointment.receipt_status = (
                "approved" if record.status == "high" else "review"
            )
            if record.status == "high" and appointment.status != "no_show":
                appointment.payment_status = (
                    "paid" if appointment.payment_mode == "full" else "deposit_paid"
                )
                appointment.paid_at = datetime.now(timezone.utc)
            else:
                appointment.payment_status = "proof_review"
        else:
            # Sin IA configurada: el comprobante queda para revisión manual.
            appointment.receipt_status = "review"
            appointment.payment_status = "proof_review"
        await db.commit()


def schedule_validation(appointment_id: str) -> None:
    try:
        asyncio.create_task(_run_validation(str(appointment_id)))
    except RuntimeError:
        logger.debug("No event loop for appointment receipt validation")
