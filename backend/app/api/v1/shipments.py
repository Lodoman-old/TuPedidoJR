from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.restaurant import Restaurant
from app.models.shipment import Shipment
from app.models.user import User
from app.schemas.shipment import (
    ShipmentCancel,
    ShipmentCreate,
    ShipmentDeliver,
    ShipmentFail,
    ShipmentOut,
    ShipmentPickup,
    ShipmentQuoteOut,
    ShipmentQuoteRequest,
    ShipmentTrackingOut,
)
from app.services.order_service import get_setting_value
from app.services.push_service import schedule_new_shipment, schedule_shipment_status
from app.services.restaurant_access import ORDER_ROLES, have_role
from app.services.shipment_service import (
    build_shipment_tracking,
    calculate_shipment_fees,
    money,
    new_delivery_code,
    new_pickup_code,
)

store_router = APIRouter()
courier_router = APIRouter()
public_router = APIRouter()


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


async def _store_or_404(db: AsyncSession, store_id: str) -> Restaurant:
    store = await db.get(Restaurant, _uuid(store_id))
    if not store:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    if store.status != "active":
        raise HTTPException(status_code=409, detail="El negocio no está activo")
    return store


async def _require_store_role(db: AsyncSession, store_id, user: User) -> None:
    if user.is_superuser:
        return
    if not await have_role(db, store_id, user, ORDER_ROLES):
        raise HTTPException(status_code=403, detail="No tienes acceso a este negocio")


async def _require_manage(db: AsyncSession, store_id, user: User) -> None:
    if user.is_superuser:
        return
    if not await have_role(db, store_id, user, ORDER_ROLES):
        raise HTTPException(status_code=403, detail="No tienes acceso a este negocio")


async def _delivery_person(db: AsyncSession, user: User) -> DeliveryPerson:
    result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == user.id)
    )
    dp = result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="Solo repartidores pueden hacer esto")
    return dp


async def _shipment_or_404(db: AsyncSession, shipment_id: str) -> Shipment:
    shipment = await db.get(Shipment, _uuid(shipment_id))
    if not shipment:
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    return shipment


async def _max_km(db: AsyncSession) -> float:
    try:
        return float(await get_setting_value(db, "DELIVERY_MAX_KM", "12"))
    except (TypeError, ValueError):
        return 12.0


async def _cod_max(db: AsyncSession) -> Decimal:
    try:
        return money(await get_setting_value(db, "SHIPMENT_COD_MAX", "1500"))
    except (TypeError, ValueError):
        return Decimal("1500.00")


# ---------------------------------------------------------------------------
# Negocio
# ---------------------------------------------------------------------------
@store_router.get("/{store_id}/shipments", response_model=list[ShipmentOut])
async def list_store_shipments(
    store_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_store_role(db, _uuid(store_id), current_user)
    stmt = select(Shipment).where(Shipment.store_id == _uuid(store_id))
    if status_filter:
        stmt = stmt.where(Shipment.status == status_filter)
    stmt = stmt.order_by(Shipment.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@store_router.post("/{store_id}/shipments/quote", response_model=ShipmentQuoteOut)
async def quote_shipment(
    store_id: str,
    body: ShipmentQuoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_store_role(db, _uuid(store_id), current_user)
    await _store_or_404(db, store_id)
    fees = await calculate_shipment_fees(
        db,
        _uuid(store_id),
        body.delivery_location.lat,
        body.delivery_location.lng,
        collect_amount=body.collect_amount,
        shipping_paid_by=body.shipping_paid_by,
    )
    max_km = await _max_km(db)
    if fees["distance_km"] is not None and fees["distance_km"] > max_km:
        raise HTTPException(
            status_code=400,
            detail=f"La dirección está fuera de la cobertura (máximo {max_km:g} km).",
        )
    return ShipmentQuoteOut(**fees)


@store_router.post(
    "/{store_id}/shipments",
    response_model=ShipmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_shipment(
    store_id: str,
    body: ShipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_store_role(db, _uuid(store_id), current_user)
    await _store_or_404(db, store_id)

    cod_max = await _cod_max(db)
    if body.collect_amount > cod_max:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El cobro contra entrega no puede superar ${cod_max:.2f}. "
                "Pide el pago por transferencia y registra el envío sin cobro."
            ),
        )

    fees = await calculate_shipment_fees(
        db,
        _uuid(store_id),
        body.delivery_location.lat,
        body.delivery_location.lng,
        collect_amount=body.collect_amount,
        shipping_paid_by=body.shipping_paid_by,
    )
    max_km = await _max_km(db)
    if fees["distance_km"] is not None and fees["distance_km"] > max_km:
        raise HTTPException(
            status_code=400,
            detail=f"La dirección está fuera de la cobertura (máximo {max_km:g} km).",
        )

    amount_to_collect = money(fees["amount_to_collect"])
    shipment = Shipment(
        store_id=_uuid(store_id),
        created_by_id=current_user.id,
        status="pending",
        recipient_name=body.recipient_name.strip(),
        recipient_phone=body.recipient_phone.strip(),
        delivery_address=body.delivery_address.strip(),
        delivery_location=(
            f"SRID=4326;POINT({body.delivery_location.lng} {body.delivery_location.lat})"
        ),
        delivery_references=(body.delivery_references or "").strip() or None,
        package_description=body.package_description.strip(),
        declared_value=money(body.declared_value),
        collect_amount=money(body.collect_amount),
        amount_to_collect=amount_to_collect,
        shipping_paid_by=body.shipping_paid_by,
        delivery_fee=fees["delivery_fee"],
        platform_fee=fees["platform_fee"],
        distance_km=fees["distance_km"],
        tip_amount=money(body.tip_amount),
        store_charge=money(fees["store_charge"]),
        store_credit=Decimal("0"),
        payment_status="pending" if fees["store_charge"] > 0 else "not_required",
        cod_status="pending" if amount_to_collect > 0 else "not_required",
        pickup_code=new_pickup_code(),
        delivery_code=new_delivery_code(),
    )
    db.add(shipment)
    await db.commit()
    await db.refresh(shipment)
    schedule_new_shipment(str(shipment.id))
    return shipment


@store_router.get("/{store_id}/shipments/{shipment_id}", response_model=ShipmentOut)
async def get_store_shipment(
    store_id: str,
    shipment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_store_role(db, _uuid(store_id), current_user)
    shipment = await _shipment_or_404(db, shipment_id)
    if str(shipment.store_id) != str(_uuid(store_id)):
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    return shipment


@store_router.post("/{store_id}/shipments/{shipment_id}/cancel", response_model=ShipmentOut)
async def cancel_store_shipment(
    store_id: str,
    shipment_id: str,
    body: ShipmentCancel,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_store_role(db, _uuid(store_id), current_user)
    shipment = await _shipment_or_404(db, shipment_id)
    if str(shipment.store_id) != str(_uuid(store_id)):
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    if shipment.status == "pending" or (
        shipment.status == "accepted" and current_user.is_superuser
    ):
        shipment.status = "cancelled"
        shipment.cancelled_at = datetime.now(timezone.utc)
        shipment.cancelled_by = current_user.id
        shipment.cancellation_reason = (body.reason or "").strip() or None
        await db.commit()
        await db.refresh(shipment)
        schedule_shipment_status(str(shipment.id), "cancelled")
        return shipment
    raise HTTPException(
        status_code=400,
        detail="Solo se puede cancelar antes de que el repartidor recoja el paquete.",
    )


# ---------------------------------------------------------------------------
# Repartidor
# ---------------------------------------------------------------------------
@courier_router.get("/shipments", response_model=list[ShipmentOut])
async def list_courier_shipments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _delivery_person(db, current_user)
    stmt = (
        select(Shipment)
        .where(
            (Shipment.delivery_person_id == dp.id)
            | (
                (Shipment.status == "pending")
                & (Shipment.delivery_person_id.is_(None))
            )
        )
        .order_by(Shipment.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@courier_router.get("/shipments/{shipment_id}", response_model=ShipmentOut)
async def get_courier_shipment(
    shipment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _delivery_person(db, current_user)
    shipment = await _shipment_or_404(db, shipment_id)
    if shipment.delivery_person_id not in (None, dp.id):
        raise HTTPException(status_code=403, detail="No tienes acceso a este envío")
    return shipment


@courier_router.patch("/shipments/{shipment_id}/accept", response_model=ShipmentOut)
async def accept_shipment(
    shipment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _delivery_person(db, current_user)
    result = await db.execute(
        select(Shipment).where(Shipment.id == _uuid(shipment_id)).with_for_update()
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    if shipment.status != "pending" or shipment.delivery_person_id is not None:
        raise HTTPException(status_code=409, detail="El envío ya fue tomado")
    shipment.delivery_person_id = dp.id
    shipment.status = "accepted"
    shipment.accepted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    schedule_shipment_status(str(shipment.id), "accepted")
    return shipment


@courier_router.patch("/shipments/{shipment_id}/pickup", response_model=ShipmentOut)
async def pickup_shipment(
    shipment_id: str,
    body: ShipmentPickup,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _delivery_person(db, current_user)
    shipment = await _shipment_or_404(db, shipment_id)
    if shipment.delivery_person_id != dp.id:
        raise HTTPException(status_code=403, detail="No eres el repartidor asignado")
    if shipment.status != "accepted":
        raise HTTPException(status_code=400, detail="El envío no está listo para recoger")
    shipment.status = "picked_up"
    shipment.picked_up_at = datetime.now(timezone.utc)
    shipment.pickup_photo_url = (body.pickup_photo_url or "").strip() or None
    await db.commit()
    await db.refresh(shipment)
    schedule_shipment_status(str(shipment.id), "picked_up")
    return shipment


@courier_router.patch("/shipments/{shipment_id}/deliver", response_model=ShipmentOut)
async def deliver_shipment(
    shipment_id: str,
    body: ShipmentDeliver,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _delivery_person(db, current_user)
    shipment = await _shipment_or_404(db, shipment_id)
    if shipment.delivery_person_id != dp.id:
        raise HTTPException(status_code=403, detail="No eres el repartidor asignado")
    if shipment.status != "picked_up":
        raise HTTPException(status_code=400, detail="Primero marca que recogiste el paquete")

    photo = (body.delivery_photo_url or "").strip() or None
    code_ok = bool(
        shipment.delivery_code
        and body.delivery_code
        and body.delivery_code.strip() == shipment.delivery_code
    )
    if not code_ok and not photo:
        raise HTTPException(
            status_code=400,
            detail="Confirma la entrega con el código del cliente o con una foto.",
        )

    expected = money(shipment.amount_to_collect)
    collected = money(body.cash_collected) if body.cash_collected is not None else expected
    if expected > 0 and collected < expected:
        raise HTTPException(
            status_code=400,
            detail=f"Debes registrar el cobro completo de ${expected:.2f}.",
        )

    shipment.status = "delivered"
    shipment.delivered_at = datetime.now(timezone.utc)
    shipment.delivery_photo_url = photo
    shipment.cash_collected = collected
    shipment.courier_earnings = money(
        (shipment.delivery_fee or 0) + (shipment.tip_amount or 0)
    )
    if (shipment.collect_amount or 0) > 0:
        shipment.cod_status = "collected"
        shipment.store_credit = money(shipment.collect_amount)
        # El repartidor se queda con su envío y su propina del efectivo que
        # cobró; el resto (producto) lo remite a la plataforma para abonarlo
        # al negocio en su liquidación.
        owed = money(collected - (shipment.courier_earnings or 0))
        if owed > 0:
            dp.pending_platform_debt = money(
                (dp.pending_platform_debt or 0) + owed
            )
    else:
        shipment.cod_status = "not_required"
    dp.total_deliveries = (dp.total_deliveries or 0) + 1

    await db.commit()
    await db.refresh(shipment)
    schedule_shipment_status(str(shipment.id), "delivered")
    return shipment


@courier_router.patch("/shipments/{shipment_id}/fail", response_model=ShipmentOut)
async def fail_shipment(
    shipment_id: str,
    body: ShipmentFail,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _delivery_person(db, current_user)
    shipment = await _shipment_or_404(db, shipment_id)
    if shipment.delivery_person_id != dp.id:
        raise HTTPException(status_code=403, detail="No eres el repartidor asignado")
    if shipment.status not in ("accepted", "picked_up"):
        raise HTTPException(status_code=400, detail="El envío ya no se puede reportar")

    try:
        percent = Decimal(await get_setting_value(db, "SHIPMENT_RETURN_PERCENT", "50"))
    except Exception:
        percent = Decimal("50")
    return_fee = money((shipment.delivery_fee or 0) * percent / Decimal("100"))
    shipment.status = "failed"
    shipment.failure_reason = body.reason.strip()
    shipment.return_fee = return_fee
    shipment.courier_earnings = return_fee
    shipment.store_charge = money((shipment.platform_fee or 0) + return_fee)
    shipment.cod_status = "not_required"
    await db.commit()
    await db.refresh(shipment)
    schedule_shipment_status(str(shipment.id), "failed")
    return shipment


# ---------------------------------------------------------------------------
# Seguimiento público (sin cuenta)
# ---------------------------------------------------------------------------
@public_router.get("/public/{token}", response_model=ShipmentTrackingOut)
async def public_shipment_tracking(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Shipment).where(Shipment.public_token == token)
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    return await build_shipment_tracking(db, shipment)
