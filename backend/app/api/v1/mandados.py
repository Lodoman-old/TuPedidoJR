from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.mandado import Mandado
from app.models.user import User
from app.schemas.mandado import (
    MandadoCreate,
    MandadoEstimateOut,
    MandadoEstimateRequest,
    MandadoOut,
    MandadoPaymentPolicyOut,
    MandadoPaymentPolicyRequest,
    MandadoPaymentProof,
    MandadoPurchase,
    MandadoTrackingOut,
)
from app.services.mandado_service import calculate_mandado_fees
from app.services.push_service import (
    schedule_mandado_status,
    schedule_new_mandado,
)
from app.services.tracking_service import build_mandado_tracking
from app.services.trust_service import mandado_payment_policy

router = APIRouter()


async def _get_setting_value(db: AsyncSession, key: str, default: str) -> str:
    from app.models.setting import Setting
    result = await db.execute(select(Setting).where(Setting.key == key))
    s = result.scalar_one_or_none()
    return s.value if s else default


@router.post("", response_model=MandadoOut, status_code=status.HTTP_201_CREATED)
async def create_mandado(
    body: MandadoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fees are shared with the public estimate endpoint so the preview and the
    # created mandado always match.
    fees = await calculate_mandado_fees(
        db,
        body.estimated_budget,
        body.delivery_location.lat,
        body.delivery_location.lng,
    )
    delivery_fee = fees["delivery_fee"]
    risk_fee = fees["risk_fee"]
    platform_fee = fees["platform_fee"]
    estimated_total = fees["estimated_total"]

    payment_method = body.payment_method
    if payment_method == "mp":
        mp_enabled = (await _get_setting_value(db, "MP_ENABLED", "false")).lower() == "true"
        if not mp_enabled:
            raise HTTPException(
                status_code=400,
                detail="Mercado Pago está deshabilitado por el momento. Paga en efectivo al recibir.",
            )
    elif payment_method == "transfer":
        transfer_enabled = (await _get_setting_value(db, "TRANSFER_ENABLED", "false")).lower() == "true"
        if not transfer_enabled:
            raise HTTPException(
                status_code=400,
                detail="La transferencia está deshabilitada por el momento. Paga en efectivo al recibir.",
            )
    elif payment_method != "cash":
        raise HTTPException(status_code=400, detail="Método de pago no válido")

    policy = await mandado_payment_policy(db, current_user, body.estimated_budget)
    if policy["requires_prepayment"] and payment_method == "cash":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Para compras de ${policy['threshold']:.2f} o más se requiere "
                "pago por transferencia antes de publicar el mandado. "
                "Si ya tienes buen historial, el sistema te permite pagar en efectivo."
            ),
        )

    prepayment_required = policy["requires_prepayment"] or payment_method != "cash"
    mandado = Mandado(
        user_id=current_user.id,
        description=body.description,
        estimated_budget=body.estimated_budget,
        delivery_fee=delivery_fee,
        risk_fee=risk_fee,
        platform_fee=platform_fee,
        estimated_total=estimated_total,
        payment_method=payment_method,
        payment_status="pending",
        prepayment_required=prepayment_required,
        prepayment_proof_url=body.payment_proof_url,
        status="pending_payment" if prepayment_required else "pending",
        delivery_address=body.delivery_address,
        delivery_location=f"SRID=4326;POINT({body.delivery_location.lng} {body.delivery_location.lat})",
    )
    db.add(mandado)
    await db.commit()
    await db.refresh(mandado)
    if not prepayment_required:
        schedule_new_mandado(str(mandado.id))
    return mandado


@router.patch("/{mandado_id}/payment-proof", response_model=MandadoOut)
async def upload_mandado_payment_proof(
    mandado_id: str,
    body: MandadoPaymentProof,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
    mandado = result.scalar_one_or_none()
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes editar este mandado")
    if not mandado.prepayment_required:
        raise HTTPException(status_code=400, detail="Este mandado no requiere prepago")
    if mandado.payment_status == "paid":
        raise HTTPException(status_code=400, detail="El pago ya fue confirmado")
    mandado.prepayment_proof_url = body.proof_url
    await db.commit()
    await db.refresh(mandado)
    return mandado


@router.post("/estimate", response_model=MandadoEstimateOut)
async def estimate_mandado(
    body: MandadoEstimateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fees = await calculate_mandado_fees(
        db,
        body.estimated_budget,
        body.delivery_location.lat,
        body.delivery_location.lng,
    )
    return MandadoEstimateOut(**fees)


@router.post("/payment-policy", response_model=MandadoPaymentPolicyOut)
async def payment_policy(
    body: MandadoPaymentPolicyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await mandado_payment_policy(db, current_user, body.estimated_budget)


@router.get("", response_model=list[MandadoOut])
async def list_mandados(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()

    if dp:
        # Delivery person sees available mandados + their own accepted ones
        stmt = (
            select(Mandado)
            .where(
                (Mandado.delivery_person_id == dp.id) |
                ((Mandado.status == "pending") & (Mandado.delivery_person_id.is_(None)))
            )
            .order_by(Mandado.created_at.desc())
        )
    else:
        # Regular user sees their own mandados
        stmt = (
            select(Mandado)
            .where(Mandado.user_id == current_user.id)
            .order_by(Mandado.created_at.desc())
        )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{mandado_id}", response_model=MandadoOut)
async def get_mandado(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
    mandado = result.scalar_one_or_none()
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.user_id != current_user.id and not current_user.is_superuser:
        dp_result = await db.execute(
            select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
        )
        dp = dp_result.scalar_one_or_none()
        if not dp or mandado.delivery_person_id != dp.id:
            raise HTTPException(status_code=403, detail="No tienes acceso a este mandado")
    return mandado


@router.get("/{mandado_id}/tracking", response_model=MandadoTrackingOut)
async def get_mandado_tracking(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
    mandado = result.scalar_one_or_none()
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")

    if mandado.user_id != current_user.id and not current_user.is_superuser:
        dp_result = await db.execute(
            select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
        )
        dp = dp_result.scalar_one_or_none()
        if not dp or mandado.delivery_person_id != dp.id:
            raise HTTPException(status_code=403, detail="No tienes acceso a este mandado")

    return await build_mandado_tracking(db, mandado)


@router.patch("/{mandado_id}/accept", response_model=MandadoOut)
async def accept_mandado(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="Solo repartidores pueden aceptar mandados")
    if not dp.is_mandadero:
        raise HTTPException(status_code=403, detail="No eres repartidor de mandados")

    result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
    mandado = result.scalar_one_or_none()
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.status != "pending":
        raise HTTPException(status_code=400, detail="Mandado no está pendiente")

    from datetime import datetime, timezone
    mandado.delivery_person_id = dp.id
    mandado.status = "accepted"
    mandado.accepted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(mandado)
    schedule_mandado_status(str(mandado.id), "accepted")
    return mandado


@router.patch("/{mandado_id}/purchase", response_model=MandadoOut)
async def purchase_mandado(
    mandado_id: str,
    body: MandadoPurchase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="Solo repartidores pueden marcar compra")

    result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
    mandado = result.scalar_one_or_none()
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.delivery_person_id != dp.id:
        raise HTTPException(status_code=403, detail="No eres el repartidor asignado")
    if mandado.status not in ("accepted", "buying"):
        raise HTTPException(status_code=400, detail="Estado inválido para marcar compra")

    from datetime import datetime, timezone
    mandado.product_total = body.product_total
    mandado.receipt_photo_url = body.receipt_photo_url
    mandado.status = "purchased"
    mandado.purchased_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(mandado)
    schedule_mandado_status(str(mandado.id), "purchased")
    return mandado


@router.patch("/{mandado_id}/deliver", response_model=MandadoOut)
async def deliver_mandado(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="Solo repartidores pueden marcar entrega")

    result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
    mandado = result.scalar_one_or_none()
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.delivery_person_id != dp.id:
        raise HTTPException(status_code=403, detail="No eres el repartidor asignado")
    if mandado.status != "purchased":
        raise HTTPException(status_code=400, detail="Debes marcar como comprado primero")

    from datetime import datetime, timezone
    mandado.status = "completed"
    mandado.payment_status = "paid"
    mandado.delivered_at = datetime.now(timezone.utc)

    # Final total uses actual product_total if available, else estimated_budget
    actual_products = mandado.product_total or mandado.estimated_budget
    mandado.final_total = actual_products + mandado.delivery_fee + mandado.risk_fee + mandado.platform_fee

    # If cash payment, accumulate platform debt
    if mandado.payment_method == "cash":
        dp.pending_platform_debt = (dp.pending_platform_debt or 0) + mandado.platform_fee

    await db.commit()
    await db.refresh(mandado)
    schedule_mandado_status(str(mandado.id), "completed")
    return mandado


@router.post("/{mandado_id}/cancel", response_model=MandadoOut)
async def cancel_mandado(
    mandado_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Mandado).where(Mandado.id == mandado_id))
    mandado = result.scalar_one_or_none()
    if not mandado:
        raise HTTPException(status_code=404, detail="Mandado no encontrado")
    if mandado.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes cancelar este mandado")
    if mandado.status not in ("pending", "pending_payment", "accepted"):
        raise HTTPException(status_code=400, detail="Solo se pueden cancelar mandados pendientes o aceptados")

    mandado.status = "cancelled"
    await db.commit()
    await db.refresh(mandado)
    schedule_mandado_status(str(mandado.id), "cancelled")
    return mandado
