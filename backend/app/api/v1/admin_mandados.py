"""Admin review for prepaid mandados."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.mandado import Mandado
from app.models.user import User
from app.services.audit_service import log_action
from app.services.push_service import schedule_mandado_status, schedule_new_mandado

router = APIRouter()


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


def _row(mandado: Mandado, user: User | None) -> dict:
    return {
        "id": str(mandado.id),
        "customer_name": user.name if user else "",
        "customer_email": user.email if user else "",
        "customer_phone": user.phone if user else "",
        "description": mandado.description,
        "estimated_budget": f"{Decimal(mandado.estimated_budget or 0):.2f}",
        "delivery_fee": f"{Decimal(mandado.delivery_fee or 0):.2f}",
        "risk_fee": f"{Decimal(mandado.risk_fee or 0):.2f}",
        "estimated_total": f"{Decimal(mandado.estimated_total or 0):.2f}",
        "payment_method": mandado.payment_method,
        "payment_status": mandado.payment_status,
        "prepayment_proof_url": mandado.prepayment_proof_url,
        "status": mandado.status,
        "created_at": mandado.created_at.isoformat() if mandado.created_at else None,
        "prepayment_confirmed_at": (
            mandado.prepayment_confirmed_at.isoformat()
            if mandado.prepayment_confirmed_at else None
        ),
    }


@router.get("/mandados/prepayments")
async def list_mandado_prepayments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(Mandado, User)
        .outerjoin(User, User.id == Mandado.user_id)
        .where(
            Mandado.prepayment_required.is_(True),
            Mandado.payment_status == "pending",
        )
        .order_by(Mandado.created_at.desc())
        .limit(100)
    )
    return [_row(mandado, user) for mandado, user in result.all()]


@router.post("/mandados/{mandado_id}/confirm-payment")
async def confirm_mandado_payment(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    mandado = await db.get(Mandado, _uuid(mandado_id))
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.payment_status == "paid":
        raise HTTPException(status_code=400, detail="El pago ya está confirmado")
    if not mandado.prepayment_required:
        raise HTTPException(status_code=400, detail="Este mandado no requiere prepago")
    mandado.payment_status = "paid"
    mandado.prepayment_confirmed_at = datetime.now(timezone.utc)
    if mandado.status == "pending_payment":
        mandado.status = "pending"
    await log_action(
        db, current_user.id, "mandado.prepayment.confirm", "mandado", mandado.id,
        {"amount": f"{Decimal(mandado.estimated_budget or 0):.2f}"},
    )
    await db.commit()
    await db.refresh(mandado)
    schedule_new_mandado(str(mandado.id))
    return _row(mandado, None)


@router.post("/mandados/{mandado_id}/reject-payment")
async def reject_mandado_payment(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    mandado = await db.get(Mandado, _uuid(mandado_id))
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.payment_status == "paid":
        raise HTTPException(status_code=400, detail="El pago ya está confirmado")
    mandado.status = "cancelled"
    await log_action(
        db, current_user.id, "mandado.prepayment.reject", "mandado", mandado.id, {},
    )
    await db.commit()
    await db.refresh(mandado)
    schedule_mandado_status(str(mandado.id), "cancelled")
    return _row(mandado, None)
