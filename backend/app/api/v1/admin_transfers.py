"""Resumen y acciones para transferencias pendientes."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.balance_payment import BalancePayment
from app.models.order import Order
from app.models.recarga_order import RecargaOrder
from app.models.receipt_validation import ReceiptValidation
from app.models.user import User
from app.services import recarga_service
from app.services.balance_payment_service import settle_balance_payment_record
from app.services.cep_validation_service import banxico_open
from app.services.order_transfer_service import settle_order_transfer
from app.services.phone_service import normalize_phone
from app.services.receipt_validation_service import revalidate_receipt

router = APIRouter()

UNRESOLVED = ("pending_cep", "review", "preapproved", "low")
RELEVANT = UNRESOLVED + ("failed",)
STATUS_LABELS = {
    "pending_cep": "Pendiente Banxico",
    "review": "En revisión",
    "preapproved": "Preaprobado",
    "low": "Revisar a fondo",
    "failed": "Falló la confirmación",
    "high": "Confirmado",
    "approved": "Aprobado",
    "rejected": "Rechazado",
}
ENTITY_LABELS = {
    "order_transfer": "Transferencia de pedido",
    "recarga_transfer": "Transferencia de recarga",
    "balance_payment": "Pago de saldo pendiente",
}


def _whatsapp_phone(phone: str | None) -> str:
    digits = normalize_phone(phone)
    if len(digits) == 10:
        return "52" + digits
    return digits


async def _record_row(
    db: AsyncSession, record: ReceiptValidation
) -> dict:
    order = None
    payment = None
    recarga = None
    customer = None
    order_link = None

    if record.entity_type == "order_transfer":
        order = await db.get(Order, record.entity_id)
        if order:
            customer = await db.get(User, order.user_id)
            order_link = f"/web/orders/{order.id}"
    elif record.entity_type == "balance_payment":
        payment = await db.get(BalancePayment, record.entity_id)
        if payment:
            customer = await db.get(User, payment.user_id)
    elif record.entity_type == "recarga_transfer":
        recarga = await db.get(RecargaOrder, record.entity_id)
        if recarga:
            customer = (
                await db.get(User, recarga.user_id)
                if recarga.user_id
                else None
            )

    amount = record.expected_amount
    if order is not None and order.total is not None:
        amount = order.total_to_pay
    elif payment is not None and payment.amount is not None:
        amount = payment.amount
    elif recarga is not None and recarga.total is not None:
        amount = recarga.total

    created = record.created_at
    age_minutes = 0
    if created:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_minutes = max(
            int((datetime.now(timezone.utc) - created).total_seconds() // 60),
            0,
        )

    short = ""
    if order is not None:
        short = str(order.id)[:8].upper()
    elif payment is not None:
        short = str(payment.id)[:8].upper()
    elif recarga is not None:
        short = str(recarga.id)[:8].upper()
    else:
        short = str(record.id)[:8].upper()

    return {
        "id": str(record.id),
        "receipt_id": str(record.id),
        "entity_type": record.entity_type,
        "entity_label": ENTITY_LABELS.get(
            record.entity_type, record.entity_type
        ),
        "amount": str(amount or Decimal("0")),
        "status": record.status,
        "status_label": STATUS_LABELS.get(record.status, record.status),
        "created_at": record.created_at.isoformat()
        if record.created_at
        else None,
        "age_minutes": age_minutes,
        "summary": record.summary,
        "error": record.error,
        "file_url": record.file_url,
        "reference": short,
        "order_link": order_link,
        "customer_name": customer.name if customer else None,
        "customer_phone": _whatsapp_phone(customer.phone if customer else None),
    }


@router.get("/transfers/summary")
async def transfers_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(ReceiptValidation)
        .where(
            ReceiptValidation.entity_type.in_(
                ("order_transfer", "balance_payment", "recarga_transfer")
            ),
            ReceiptValidation.status.in_(RELEVANT),
        )
        .order_by(ReceiptValidation.created_at.desc())
        .limit(200)
    )
    records = list(result.scalars().all())

    counts = {status: 0 for status in RELEVANT}
    unresolved_amount = Decimal("0")
    older_than_1h = 0
    cutoff = datetime.now(timezone.utc).timestamp() - 3600

    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
        if record.status not in UNRESOLVED:
            continue
        if record.expected_amount is not None:
            unresolved_amount += Decimal(record.expected_amount)
        created = record.created_at
        if created:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created.timestamp() <= cutoff:
                older_than_1h += 1

    rows = [await _record_row(db, record) for record in records[:100]]
    unresolved_count = sum(counts.get(status, 0) for status in UNRESOLVED)
    return {
        "totals": {
            "unresolved": unresolved_count,
            "amount": str(unresolved_amount),
            "older_than_1h": older_than_1h,
            "pending_cep": counts.get("pending_cep", 0),
            "review": counts.get("review", 0),
            "preapproved": counts.get("preapproved", 0),
            "low": counts.get("low", 0),
            "failed": counts.get("failed", 0),
        },
        "records": rows,
    }


@router.post("/transfers/revalidate")
async def revalidate_pending_transfers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    if not banxico_open():
        raise HTTPException(
            status_code=400,
            detail=(
                "Banxico valida transferencias de 09:30 a 23:00. "
                "Intenta dentro de ese horario."
            ),
        )

    result = await db.execute(
        select(ReceiptValidation)
        .where(
            ReceiptValidation.entity_type.in_(
                ("order_transfer", "balance_payment", "recarga_transfer")
            ),
            ReceiptValidation.status.in_(UNRESOLVED),
        )
        .order_by(ReceiptValidation.created_at)
        .limit(20)
    )
    records = list(result.scalars().all())
    processed = 0
    confirmed = 0

    for record in records:
        record = await revalidate_receipt(db, record)
        if record.status == "high":
            if record.entity_type == "order_transfer":
                await settle_order_transfer(db, record, True)
            elif record.entity_type == "balance_payment":
                await settle_balance_payment_record(db, record, True)
            elif record.entity_type == "recarga_transfer":
                await recarga_service.settle_transfer_receipt(
                    db, record, approved=True
                )
            confirmed += 1
        await db.commit()
        processed += 1

    return {"processed": processed, "confirmed": confirmed}
