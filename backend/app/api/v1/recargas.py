from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_superuser
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.recarga_order import RecargaOrder
from app.models.user import User
from app.schemas.recarga import RecargaComplete, RecargaCreate, RecargaFail, RecargaOut
from app.services import recarga_service

router = APIRouter()
admin_router = APIRouter()

# Recargas en pausa hasta integrar al proveedor y el pago validado por Banxico.
# El historial y las acciones administrativas siguen disponibles para registros
# anteriores, pero no se pueden crear solicitudes nuevas.
RECARGAS_AVAILABLE = False


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


def _out(recarga: RecargaOrder, courier_name: str | None = None) -> RecargaOut:
    data = RecargaOut.model_validate(recarga)
    data.courier_name = courier_name
    data.order_code = str(recarga.order_id)[:8] if recarga.order_id else None
    return data


async def _courier_for_user(db: AsyncSession, user: User) -> DeliveryPerson | None:
    result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == user.id)
    )
    return result.scalar_one_or_none()


@router.post("", response_model=RecargaOut, status_code=201)
async def create_recarga(
    body: RecargaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not RECARGAS_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Las recargas estarán disponibles próximamente.",
        )
    dp = await _courier_for_user(db, current_user)
    order = None
    if body.order_id:
        order = await db.get(Order, body.order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        if dp is None or order.delivery_person_id != dp.id:
            raise HTTPException(status_code=403, detail="Ese pedido no te pertenece")
    try:
        if body.payment_method == "cash":
            if dp is None:
                raise HTTPException(
                    status_code=400,
                    detail="Las recargas en efectivo solo las puede cobrar un repartidor",
                )
            recarga = await recarga_service.create_cash_recarga(
                db, dp,
                company=body.company,
                phone=body.phone,
                amount=body.amount,
                order=order,
                customer_name=body.customer_name,
            )
        else:
            recarga = await recarga_service.create_transfer_recarga(
                db, current_user,
                company=body.company,
                phone=body.phone,
                amount=body.amount,
                customer_name=body.customer_name,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga, current_user.name if dp else None)


@router.get("/my", response_model=list[RecargaOut])
async def my_recargas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _courier_for_user(db, current_user)
    if dp is not None:
        rows = await recarga_service.list_recargas_for_courier(db, dp)
    else:
        rows = await recarga_service.list_recargas_for_user(db, current_user.id)
    return [_out(row, current_user.name if dp else None) for row in rows]


@router.post("/{recarga_id}/retry", response_model=RecargaOut)
async def retry_my_recarga(
    recarga_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    dp = await _courier_for_user(db, current_user)
    if dp is None or recarga.delivery_person_id != dp.id:
        raise HTTPException(status_code=403, detail="No puedes reintentar esta recarga")
    try:
        recarga = await recarga_service.retry_recarga(db, recarga)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga, current_user.name)


@admin_router.get("/recargas", response_model=list[RecargaOut])
async def admin_recargas(
    status_filter: str | None = None,
    q: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    query = (
        select(RecargaOrder, User)
        .outerjoin(DeliveryPerson, DeliveryPerson.id == RecargaOrder.delivery_person_id)
        .outerjoin(User, User.id == DeliveryPerson.user_id)
        .order_by(RecargaOrder.created_at.desc())
        .limit(min(max(limit, 1), 300))
    )
    if status_filter in ("requested", "pending", "completed", "failed", "refunded"):
        query = query.where(RecargaOrder.status == status_filter)
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        query = query.where(or_(
            RecargaOrder.phone.ilike(like),
            RecargaOrder.company.ilike(like),
            RecargaOrder.provider_reference.ilike(like),
        ))
    result = await db.execute(query)
    return [_out(row, user.name if user else None) for row, user in result.all()]


@admin_router.post("/recargas/{recarga_id}/confirm-payment", response_model=RecargaOut)
async def admin_confirm_payment(
    recarga_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    try:
        recarga = await recarga_service.confirm_transfer_payment(db, recarga)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga)


@admin_router.post("/recargas/{recarga_id}/complete", response_model=RecargaOut)
async def admin_complete(
    recarga_id: str,
    body: RecargaComplete | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    try:
        recarga = await recarga_service.complete_recarga(
            db, recarga,
            reference=body.provider_reference if body else None,
            notes=body.notes if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga)


@admin_router.post("/recargas/{recarga_id}/fail", response_model=RecargaOut)
async def admin_fail(
    recarga_id: str,
    body: RecargaFail | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    try:
        recarga = await recarga_service.fail_recarga(
            db, recarga, None,
            refund=body.refund if body else True,
            error_message=body.error_message if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga)


@admin_router.post("/recargas/{recarga_id}/retry", response_model=RecargaOut)
async def admin_retry(
    recarga_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    try:
        recarga = await recarga_service.retry_recarga(db, recarga)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga)
