"""Panel administrativo de incidencias de entrega."""
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.delivery_incident import DeliveryIncident
from app.models.mandado import Mandado
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.shipment import Shipment
from app.models.user import User
from app.services.audit_service import log_action
from app.services.incident_service import (
    REASON_LABELS,
    STATUS_LABELS,
    authorize_incident,
    discard_item,
    mark_custody,
    resolve_incident,
    return_to_business,
    schedule_redelivery,
)

router = APIRouter()


class CustodyBody(BaseModel):
    photo_url: str | None = None


class RedeliverBody(BaseModel):
    fee: Decimal | None = None


class ReturnBody(BaseModel):
    notes: str | None = None


class DiscardBody(BaseModel):
    notes: str | None = None
    photo_url: str | None = None
    courier_fault: bool = False


class AuthorizeBody(BaseModel):
    absorb: bool
    notes: str | None = None


class ResolveBody(BaseModel):
    notes: str | None = None


def _money(value) -> float:
    return float(value or 0)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _serialize(incident: DeliveryIncident, entity_label: str | None = None) -> dict:
    return {
        "id": str(incident.id),
        "entity_type": incident.entity_type,
        "entity_id": str(incident.entity_id),
        "entity_label": entity_label,
        "reason_code": incident.reason_code,
        "reason": REASON_LABELS.get(incident.reason_code, incident.reason_code),
        "status": incident.status,
        "status_label": STATUS_LABELS.get(incident.status, incident.status),
        "item_kind": incident.item_kind,
        "notes": incident.notes,
        "photo_url": incident.photo_url,
        "product_amount": _money(incident.product_amount),
        "delivery_amount": _money(incident.delivery_amount),
        "redelivery_fee": _money(incident.redelivery_fee),
        "courier_pay": _money(incident.courier_pay),
        "business_pay": _money(incident.business_pay),
        "customer_refund": _money(incident.customer_refund),
        "customer_debt": _money(incident.customer_debt),
        "platform_cost": _money(incident.platform_cost),
        "requires_authorization": incident.requires_authorization,
        "resolution_notes": incident.resolution_notes,
        "custody_code": incident.custody_code,
        "holding_until": _iso(incident.holding_until),
        "created_at": _iso(incident.created_at),
        "resolved_at": _iso(incident.resolved_at),
        "holds_hours": 48 if incident.item_kind == "food" else None,
    }


async def _entity_label(db: AsyncSession, incident: DeliveryIncident) -> str:
    if incident.entity_type == "order":
        result = await db.execute(
            select(Order, Restaurant.name, User.name)
            .outerjoin(Restaurant, Restaurant.id == Order.restaurant_id)
            .outerjoin(User, User.id == Order.user_id)
            .where(Order.id == incident.entity_id)
        )
        row = result.first()
        if row:
            order, resto, customer = row
            return f"Pedido #{str(order.id)[:8]} · {resto or 'Negocio'} · {customer or 'Cliente'}"
    elif incident.entity_type == "mandado":
        mandado = await db.get(Mandado, incident.entity_id)
        if mandado:
            return f"Mandado #{str(mandado.id)[:8]} · {mandado.description[:60]}"
    elif incident.entity_type == "shipment":
        shipment = await db.get(Shipment, incident.entity_id)
        if shipment:
            return f"Envío #{str(shipment.id)[:8]} · {shipment.recipient_name}"
    return f"{incident.entity_type} #{str(incident.entity_id)[:8]}"


async def _get_incident(db: AsyncSession, incident_id: str) -> DeliveryIncident:
    try:
        from uuid import UUID

        uid = UUID(incident_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc
    incident = await db.get(DeliveryIncident, uid)
    if not incident:
        raise HTTPException(status_code=404, detail="Incidencia no encontrada")
    return incident


@router.get("/incidents")
async def list_incidents(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    stmt = select(DeliveryIncident).order_by(DeliveryIncident.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(DeliveryIncident.status == status)
    result = await db.execute(stmt)
    incidents = result.scalars().all()
    data = []
    for incident in incidents:
        data.append(_serialize(incident, await _entity_label(db, incident)))
    return {
        "incidents": data,
        "reason_labels": REASON_LABELS,
        "status_labels": STATUS_LABELS,
    }


@router.post("/incidents/{incident_id}/custody")
async def incident_custody(
    incident_id: str,
    body: CustodyBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    incident = await _get_incident(db, incident_id)
    try:
        await mark_custody(db, incident, photo_url=body.photo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(db, current_user.id, "incident.custody", "delivery_incident", incident.id, {})
    await db.commit()
    await db.refresh(incident)
    return _serialize(incident, await _entity_label(db, incident))


@router.post("/incidents/{incident_id}/redeliver")
async def incident_redeliver(
    incident_id: str,
    body: RedeliverBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    incident = await _get_incident(db, incident_id)
    try:
        await schedule_redelivery(db, incident, fee=body.fee)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(db, current_user.id, "incident.redeliver", "delivery_incident", incident.id, {})
    await db.commit()
    await db.refresh(incident)
    return _serialize(incident, await _entity_label(db, incident))


@router.post("/incidents/{incident_id}/return")
async def incident_return(
    incident_id: str,
    body: ReturnBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    incident = await _get_incident(db, incident_id)
    try:
        await return_to_business(db, incident, notes=body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(db, current_user.id, "incident.return", "delivery_incident", incident.id, {})
    await db.commit()
    await db.refresh(incident)
    return _serialize(incident, await _entity_label(db, incident))


@router.post("/incidents/{incident_id}/discard")
async def incident_discard(
    incident_id: str,
    body: DiscardBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    incident = await _get_incident(db, incident_id)
    try:
        await discard_item(
            db, incident,
            notes=body.notes,
            photo_url=body.photo_url,
            courier_fault=body.courier_fault,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(db, current_user.id, "incident.discard", "delivery_incident", incident.id, {})
    await db.commit()
    await db.refresh(incident)
    return _serialize(incident, await _entity_label(db, incident))


@router.post("/incidents/{incident_id}/authorize")
async def incident_authorize(
    incident_id: str,
    body: AuthorizeBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    incident = await _get_incident(db, incident_id)
    try:
        await authorize_incident(
            db, incident, current_user.id, absorb=body.absorb, notes=body.notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(
        db, current_user.id, "incident.authorize", "delivery_incident", incident.id,
        {"absorb": body.absorb},
    )
    await db.commit()
    await db.refresh(incident)
    return _serialize(incident, await _entity_label(db, incident))


@router.post("/incidents/{incident_id}/resolve")
async def incident_resolve(
    incident_id: str,
    body: ResolveBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    incident = await _get_incident(db, incident_id)
    await resolve_incident(db, incident, notes=body.notes)
    await log_action(db, current_user.id, "incident.resolve", "delivery_incident", incident.id, {})
    await db.commit()
    await db.refresh(incident)
    return _serialize(incident, await _entity_label(db, incident))
