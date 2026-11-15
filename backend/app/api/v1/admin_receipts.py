from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.receipt_validation import ReceiptValidation
from app.models.user import User
from app.services.receipt_validation_service import revalidate_receipt

router = APIRouter()

ENTITY_LABELS = {
    "mandado_prepayment": "Prepago de mandado",
    "mandado_purchase": "Ticket de compra de mandado",
    "reservation_deposit": "Depósito de reservación",
}
KIND_LABELS = {
    "purchase_receipt": "Ticket de compra",
    "transfer_receipt": "Transferencia",
}
STATUS_LABELS = {
    "high": "Se puede aprobar",
    "review": "Revisar",
    "low": "Revisar a fondo",
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
