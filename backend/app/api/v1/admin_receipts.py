from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.appointment import Appointment
from app.models.order import Order
from app.models.rental_booking import RentalBooking
from app.models.receipt_validation import ReceiptValidation
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.receipt_validation_service import revalidate_receipt
from app.services.affiliation_qr_service import send_affiliation_qr_email
from app.services.push_service import schedule_appointment_paid

router = APIRouter()

ENTITY_LABELS = {
    "mandado_prepayment": "Prepago de mandado",
    "mandado_purchase": "Ticket de compra de mandado",
    "reservation_deposit": "Depósito de reservación",
    "appointment_payment": "Pago de cita",
    "rental_payment": "Pago de renta",
    "affiliation_payment": "Afiliación anual",
    "order_transfer": "Transferencia de pedido",
}
KIND_LABELS = {
    "purchase_receipt": "Ticket de compra",
    "transfer_receipt": "Transferencia",
}
STATUS_LABELS = {
    "high": "Se puede aprobar",
    "review": "Revisar",
    "low": "Revisar a fondo",
    "approved": "Aprobado",
    "rejected": "Rechazado",
}


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


def _row(record: ReceiptValidation) -> dict:
    return {
        "id": str(record.id),
        "entity_type": record.entity_type,
        "entity_label": ENTITY_LABELS.get(record.entity_type, record.entity_type),
        "entity_id": str(record.entity_id),
        "file_url": record.file_url,
        "expected_kind": record.expected_kind,
        "expected_kind_label": KIND_LABELS.get(record.expected_kind, record.expected_kind),
        "expected_amount": str(record.expected_amount) if record.expected_amount is not None else None,
        "plan_months": record.plan_months,
        "expected_date": record.expected_date.isoformat() if record.expected_date else None,
        "expected_recipient": record.expected_recipient,
        "document_type": record.document_type,
        "confidence": record.confidence,
        "status": record.status,
        "status_label": STATUS_LABELS.get(record.status, record.status),
        "extracted": record.extracted or {},
        "issues": record.issues or [],
        "summary": record.summary,
        "provider": record.provider,
        "model": record.model,
        "error": record.error,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.get("/receipts")
async def list_receipts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(ReceiptValidation)
        .order_by(ReceiptValidation.created_at.desc())
        .limit(300)
    )
    return [_row(row) for row in result.scalars().all()]


@router.post("/receipts/{receipt_id}/revalidate")
async def revalidate(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    record = await db.get(ReceiptValidation, _uuid(receipt_id))
    if not record:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    record = await revalidate_receipt(db, record)
    return _row(record)


async def _settle_entity(db: AsyncSession, record: ReceiptValidation, approved: bool) -> bool:
    if record.entity_type == "appointment_payment":
        await _settle_appointment(db, record, approved)
    elif record.entity_type == "rental_payment":
        await _settle_rental(db, record, approved)
    elif record.entity_type == "affiliation_payment":
        return await _settle_affiliation(db, record, approved)
    elif record.entity_type == "order_transfer":
        await _settle_order(db, record, approved)
    return False


async def _settle_order(
    db: AsyncSession, record: ReceiptValidation, approved: bool
) -> None:
    order = await db.get(Order, record.entity_id)
    if not order:
        return
    if not approved:
        if order.payment_status != "approved":
            order.cep_status = "rejected"
        return
    if order.payment_status == "approved":
        return

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

    from app.services.payout_service import credit_courier_for_order

    await credit_courier_for_order(db, order)


async def _settle_appointment(db: AsyncSession, record: ReceiptValidation, approved: bool) -> None:
    appointment = await db.get(Appointment, record.entity_id)
    if not appointment:
        return
    if approved:
        appointment.receipt_status = "approved"
        appointment.payment_status = (
            "paid" if appointment.payment_mode == "full" else "deposit_paid"
        )
        appointment.paid_at = datetime.now(timezone.utc)
        schedule_appointment_paid(str(appointment.id))
    else:
        appointment.receipt_status = "rejected"
        appointment.payment_status = "proof_rejected"
        appointment.paid_at = None


async def _settle_rental(db: AsyncSession, record: ReceiptValidation, approved: bool) -> None:
    booking = await db.get(RentalBooking, record.entity_id)
    if not booking:
        return
    if approved:
        booking.receipt_status = "approved"
        booking.payment_status = (
            "paid" if booking.payment_mode == "full" else "deposit_paid"
        )
        booking.paid_at = datetime.now(timezone.utc)
    else:
        booking.receipt_status = "rejected"
        booking.payment_status = "proof_rejected"
        booking.paid_at = None


async def _settle_affiliation(db: AsyncSession, record: ReceiptValidation, approved: bool) -> bool:
    restaurant = await db.get(Restaurant, record.entity_id)
    if not restaurant:
        return False
    extracted = dict(record.extracted or {})
    months = int(record.plan_months or 12)
    days = 365 if months == 12 else months * 30
    newly_applied = False
    if approved:
        if not extracted.get("applied"):
            base = date.today()
            current = restaurant.affiliation_expires_at
            if current and current >= base:
                base = current
            extracted["previous_expires_at"] = current.isoformat() if current else None
            restaurant.affiliation_expires_at = base + timedelta(days=days)
            restaurant.affiliation_reminder_on = None
            extracted["applied"] = True
            extracted["applied_months"] = months
            newly_applied = True
    else:
        if extracted.get("applied"):
            previous = extracted.get("previous_expires_at")
            restaurant.affiliation_expires_at = date.fromisoformat(previous) if previous else None
            restaurant.affiliation_reminder_on = None
            extracted["applied"] = False
    record.extracted = extracted
    return newly_applied


@router.post("/receipts/{receipt_id}/approve")
async def approve_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    record = await db.get(ReceiptValidation, _uuid(receipt_id))
    if not record:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    record.status = "approved"
    newly_affiliated = await _settle_entity(db, record, True)
    await db.commit()
    await db.refresh(record)
    row = _row(record)
    if newly_affiliated:
        restaurant = await db.get(Restaurant, record.entity_id)
        if restaurant:
            sent, detail = await send_affiliation_qr_email(db, restaurant)
            row["qr_email_sent"] = sent
            row["qr_email_detail"] = None if sent else detail
    return row


@router.post("/receipts/{receipt_id}/reject")
async def reject_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    record = await db.get(ReceiptValidation, _uuid(receipt_id))
    if not record:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    record.status = "rejected"
    await _settle_entity(db, record, False)
    await db.commit()
    await db.refresh(record)
    return _row(record)
