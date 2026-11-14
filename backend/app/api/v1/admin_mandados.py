"""Admin review for prepaid mandados."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
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
        "advance_amount": f"{Decimal(mandado.advance_amount or 0):.2f}",
        "advance_status": mandado.advance_status,
        "advance_difference": (
            f"{Decimal(mandado.advance_difference):.2f}"
            if mandado.advance_difference is not None else None
        ),
        "advance_delivered_at": (
            mandado.advance_delivered_at.isoformat()
            if mandado.advance_delivered_at else None
        ),
        "advance_settled_at": (
            mandado.advance_settled_at.isoformat()
            if mandado.advance_settled_at else None
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


@router.get("/mandados/advances")
async def list_mandado_advances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    courier_user = aliased(User)
    result = await db.execute(
        select(Mandado, User, DeliveryPerson, courier_user)
        .outerjoin(User, User.id == Mandado.user_id)
        .outerjoin(DeliveryPerson, DeliveryPerson.id == Mandado.delivery_person_id)
        .outerjoin(courier_user, courier_user.id == DeliveryPerson.user_id)
        .where(
            Mandado.prepayment_required.is_(True),
            Mandado.advance_status.in_(("pending", "delivered", "used")),
        )
        .order_by(Mandado.created_at.desc())
        .limit(100)
    )
    rows = []
    for mandado, customer, courier, courier_account in result.all():
        row = _row(mandado, customer)
        row["courier_name"] = courier_account.name if courier_account else ""
        row["courier_phone"] = courier_account.phone if courier_account else ""
        row["courier_bank_name"] = courier.bank_name if courier else ""
        row["courier_clabe"] = courier.bank_clabe if courier else ""
        rows.append(row)
    return rows


@router.post("/mandados/{mandado_id}/advance-delivered")
async def deliver_mandado_advance(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    mandado = await db.get(Mandado, _uuid(mandado_id))
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if not mandado.prepayment_required:
        raise HTTPException(status_code=400, detail="Este mandado no requiere adelanto")
    if mandado.advance_status != "pending":
        raise HTTPException(status_code=400, detail="El adelanto no está pendiente")
    if mandado.status not in ("accepted", "buying"):
        raise HTTPException(
            status_code=400,
            detail="El repartidor debe aceptar el mandado antes de entregar el adelanto",
        )
    mandado.advance_status = "delivered"
    mandado.advance_delivered_at = datetime.now(timezone.utc)
    await log_action(
        db, current_user.id, "mandado.advance.delivered", "mandado", mandado.id,
        {"amount": f"{Decimal(mandado.advance_amount or 0):.2f}"},
    )
    await db.commit()
    await db.refresh(mandado)
    return _row(mandado, None)


@router.post("/mandados/{mandado_id}/advance-settle")
async def settle_mandado_advance(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    mandado = await db.get(Mandado, _uuid(mandado_id))
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.advance_status not in ("delivered", "used"):
        raise HTTPException(status_code=400, detail="El adelanto no está por liquidar")
    mandado.advance_status = "settled"
    mandado.advance_settled_at = datetime.now(timezone.utc)
    await log_action(
        db, current_user.id, "mandado.advance.settled", "mandado", mandado.id,
        {"difference": f"{Decimal(mandado.advance_difference or 0):.2f}"},
    )
    await db.commit()
    await db.refresh(mandado)
    return _row(mandado, None)


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
    if mandado.prepayment_required:
        mandado.advance_amount = mandado.estimated_budget or Decimal("0")
        mandado.advance_status = "pending"
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
