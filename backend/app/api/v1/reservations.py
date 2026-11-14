from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.menu_item import MenuItem
from app.models.reservation import Reservation
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.reservation import (
    ReservationCreate,
    ReservationDepositProof,
    ReservationOut,
    ReservationStatusUpdate,
)
from app.services.order_service import get_setting_value, resolve_item_options
from app.services.push_service import (
    schedule_new_reservation,
    schedule_reservation_status,
)
from app.services.restaurant_access import MANAGE_ROLES, ORDER_ROLES, have_role

router = APIRouter()
restaurant_router = APIRouter()


def _out(reservation: Reservation, restaurant: Restaurant | None = None, user: User | None = None) -> ReservationOut:
    data = ReservationOut.model_validate(reservation)
    if restaurant:
        data.restaurant_name = restaurant.name
        data.restaurant_address = restaurant.address
        data.restaurant_phone = restaurant.phone
        data.restaurant_slug = restaurant.slug
        data.restaurant_logo_url = restaurant.logo_url
    if user:
        data.user_name = user.name
        data.user_phone = user.phone
        data.user_email = user.email
    return data


async def _load(db: AsyncSession, reservation_id: str):
    result = await db.execute(
        select(Reservation, Restaurant, User)
        .join(Restaurant, Restaurant.id == Reservation.restaurant_id)
        .join(User, User.id == Reservation.user_id)
        .where(Reservation.id == reservation_id)
    )
    return result.first()


async def _money_setting(db: AsyncSession, key: str, default: str) -> Decimal:
    try:
        return Decimal(str(await get_setting_value(db, key, default)))
    except Exception:
        return Decimal(default)


async def _restaurant_fee(db: AsyncSession, restaurant: Restaurant) -> Decimal:
    raw = restaurant.fixed_fee
    if raw is None:
        raw = await get_setting_value(db, "APP_FIXED_RESTAURANT_FEE", "5.0")
    try:
        return Decimal(str(raw or 0))
    except Exception:
        return Decimal("5.0")


async def _can_view(db: AsyncSession, reservation: Reservation, current_user: User) -> bool:
    if current_user.is_superuser or reservation.user_id == current_user.id:
        return True
    return await have_role(db, reservation.restaurant_id, current_user, ORDER_ROLES)


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    body: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Endpoint kept for compatibility; restaurant is taken from body.restaurant_id
    raise HTTPException(status_code=400, detail="Usa /restaurants/{id}/reservations")


@router.get("", response_model=list[ReservationOut])
async def list_my_reservations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Reservation, Restaurant)
        .join(Restaurant, Restaurant.id == Reservation.restaurant_id)
        .where(Reservation.user_id == current_user.id)
        .order_by(Reservation.reservation_at.desc())
    )
    return [_out(reservation, restaurant, current_user) for reservation, restaurant in result.all()]


@router.get("/{reservation_id}", response_model=ReservationOut)
async def get_reservation(
    reservation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _load(db, reservation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    reservation, restaurant, user = row
    if not await _can_view(db, reservation, current_user):
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación")
    return _out(reservation, restaurant, user)


@router.patch("/{reservation_id}/deposit-proof", response_model=ReservationOut)
async def upload_deposit_proof(
    reservation_id: str,
    body: ReservationDepositProof,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _load(db, reservation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    reservation, restaurant, user = row
    if reservation.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="No puedes editar esta reservación")
    reservation.deposit_proof_url = body.proof_url
    await db.commit()
    await db.refresh(reservation)
    return _out(reservation, restaurant, user)


@router.post("/{reservation_id}/cancel", response_model=ReservationOut)
async def cancel_reservation(
    reservation_id: str,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _load(db, reservation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    reservation, restaurant, user = row

    if current_user.is_superuser:
        role = "admin"
    elif await have_role(db, reservation.restaurant_id, current_user, MANAGE_ROLES):
        role = "restaurant"
    elif reservation.user_id == current_user.id:
        role = "customer"
    else:
        raise HTTPException(status_code=403, detail="No puedes cancelar esta reservación")

    if reservation.status in ("completed", "cancelled", "no_show"):
        raise HTTPException(status_code=400, detail="La reservación ya no se puede cancelar")

    now = datetime.now(timezone.utc)
    reason = (body or {}).get("reason") if isinstance(body, dict) else None
    if reservation.deposit_status == "paid" and reservation.deposit_amount > 0:
        if role == "customer" and now >= reservation.reservation_at - timedelta(hours=2):
            reservation.deposit_status = "retained"
            reservation.deposit_settlement_status = "pending"
        else:
            reservation.deposit_status = "refund_pending"
            reservation.deposit_settlement_status = "refund_pending"
    elif reservation.deposit_status == "pending":
        reservation.deposit_status = "cancelled"
        reservation.deposit_settlement_status = "not_required"

    reservation.status = "cancelled"
    reservation.cancelled_at = now
    reservation.cancelled_by = current_user.id
    reservation.cancellation_reason = (reason or "").strip() or None
    await db.commit()
    await db.refresh(reservation)
    schedule_reservation_status(str(reservation.id))
    return _out(reservation, restaurant, user)


@restaurant_router.post("/{restaurant_id}/reservations", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create_restaurant_reservation(
    restaurant_id: str,
    body: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant or restaurant.status != "active":
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not restaurant.reservations_enabled:
        raise HTTPException(status_code=409, detail="Este restaurante no acepta reservaciones")
    if restaurant.affiliation_expires_at is None or restaurant.affiliation_expires_at < datetime.now(timezone.utc).date():
        raise HTTPException(status_code=409, detail="El restaurante no está disponible")

    now = datetime.now(timezone.utc)
    reservation_at = body.reservation_at
    if reservation_at.tzinfo is None:
        reservation_at = reservation_at.replace(tzinfo=timezone.utc)
    min_advance = max(int(restaurant.reservation_min_advance_min or 120), 0)
    if reservation_at < now + timedelta(minutes=min_advance):
        hours = max(min_advance / 60, 0)
        raise HTTPException(
            status_code=400,
            detail=f"La reservación debe hacerse con al menos {hours:g} hora(s) de anticipación",
        )
    if reservation_at > now + timedelta(days=60):
        raise HTTPException(status_code=400, detail="Solo se puede reservar con 60 días de anticipación")

    items = []
    subtotal = Decimal("0.00")
    for entry in body.items:
        menu_result = await db.execute(select(MenuItem).where(MenuItem.id == entry.menu_item_id))
        menu_item = menu_result.scalar_one_or_none()
        if not menu_item or menu_item.restaurant_id != restaurant.id:
            raise HTTPException(status_code=400, detail="Uno de los platillos no pertenece al restaurante")
        if not menu_item.is_available:
            raise HTTPException(status_code=400, detail=f"{menu_item.name} no está disponible")
        try:
            unit_price, selected = await resolve_item_options(db, menu_item, entry.option_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        subtotal += unit_price * entry.quantity
        items.append({
            "menu_item_id": str(menu_item.id),
            "name": menu_item.name,
            "quantity": entry.quantity,
            "unit_price": f"{unit_price:.2f}",
            "options": [
                {
                    "option_id": str(opt.get("option_id") or ""),
                    "group_name": opt.get("group_name"),
                    "name": opt.get("name"),
                    "price_delta": f"{Decimal(str(opt.get('price_delta') or 0)):.2f}",
                    "portion": float(opt.get("portion") or 1),
                }
                for opt in selected
            ],
        })

    service_fee = await _money_setting(db, "APP_FLAT_USAGE_FEE", "5.0")
    commission = await _restaurant_fee(db, restaurant)
    deposit_percent = Decimal(str(restaurant.reservation_deposit_percent or 20))
    has_preorder = bool(items)
    if has_preorder:
        deposit_amount = (subtotal * deposit_percent / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        remaining = (subtotal - deposit_amount).quantize(Decimal("0.01"))
        reservation_status = "pending_deposit"
        deposit_status_value = "pending"
        service_fee_cash = False
        settlement = "pending"
    else:
        deposit_amount = Decimal("0.00")
        remaining = Decimal("0.00")
        reservation_status = "requested"
        deposit_status_value = "not_required"
        service_fee_cash = True
        settlement = "not_required"

    reservation = Reservation(
        restaurant_id=restaurant.id,
        user_id=current_user.id,
        reservation_at=reservation_at,
        party_size=body.party_size,
        status=reservation_status,
        notes=(body.notes or "").strip() or None,
        preorder_items=items or None,
        preorder_subtotal=subtotal,
        service_fee=service_fee,
        service_fee_cash=service_fee_cash,
        service_fee_status="pending" if service_fee_cash else "paid_online",
        deposit_percent=deposit_percent,
        deposit_amount=deposit_amount,
        deposit_status=deposit_status_value,
        deposit_method=body.deposit_method if has_preorder else None,
        deposit_proof_url=body.deposit_proof_url if has_preorder else None,
        commission_amount=commission,
        commission_status="pending",
        remaining_to_charge=remaining,
        deposit_settlement_status=settlement,
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    schedule_new_reservation(str(reservation.id), deposit_pending=has_preorder)
    return _out(reservation, restaurant, current_user)


@restaurant_router.get("/{restaurant_id}/reservations", response_model=list[ReservationOut])
async def list_restaurant_reservations(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await have_role(db, restaurant_id, current_user, ORDER_ROLES):
        raise HTTPException(status_code=403, detail="No puedes ver las reservaciones de este restaurante")
    result = await db.execute(
        select(Reservation, Restaurant, User)
        .join(Restaurant, Restaurant.id == Reservation.restaurant_id)
        .join(User, User.id == Reservation.user_id)
        .where(Reservation.restaurant_id == restaurant_id)
        .order_by(Reservation.reservation_at.desc())
    )
    return [_out(reservation, restaurant, user) for reservation, restaurant, user in result.all()]


@restaurant_router.patch(
    "/{restaurant_id}/reservations/{reservation_id}/status",
    response_model=ReservationOut,
)
async def update_reservation_status(
    restaurant_id: str,
    reservation_id: str,
    body: ReservationStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await have_role(db, restaurant_id, current_user, MANAGE_ROLES) and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="No puedes cambiar esta reservación")
    row = await _load(db, reservation_id)
    if not row or str(row[0].restaurant_id) != str(restaurant_id):
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    reservation, restaurant, user = row
    now = datetime.now(timezone.utc)

    if body.status == "confirmed":
        if reservation.deposit_status not in ("paid", "not_required"):
            raise HTTPException(status_code=400, detail="El depósito aún no está validado")
        reservation.status = "confirmed"
        reservation.confirmed_at = now
    elif body.status == "rejected":
        reservation.status = "rejected"
        reservation.cancelled_at = now
        reservation.cancellation_reason = body.reason
        if reservation.deposit_status == "paid" and reservation.deposit_amount > 0:
            reservation.deposit_status = "refund_pending"
            reservation.deposit_settlement_status = "refund_pending"
        elif reservation.deposit_status == "pending":
            reservation.deposit_status = "cancelled"
            reservation.deposit_settlement_status = "not_required"
    elif body.status == "seated":
        if reservation.status != "confirmed":
            raise HTTPException(status_code=400, detail="La reservación no está confirmada")
        reservation.status = "seated"
        reservation.seated_at = now
    elif body.status == "completed":
        if reservation.status not in ("confirmed", "seated"):
            raise HTTPException(status_code=400, detail="La reservación no está activa")
        reservation.status = "completed"
        reservation.completed_at = now
    elif body.status == "no_show":
        if reservation.status != "confirmed":
            raise HTTPException(status_code=400, detail="La reservación no está confirmada")
        reservation.status = "no_show"
        reservation.no_show_at = now
        if reservation.deposit_status == "paid" and reservation.deposit_amount > 0:
            reservation.deposit_status = "retained"
            reservation.deposit_settlement_status = "pending"
    elif body.status == "cancelled":
        reservation.status = "cancelled"
        reservation.cancelled_at = now
        reservation.cancelled_by = current_user.id
        reservation.cancellation_reason = body.reason
        if reservation.deposit_status == "paid" and reservation.deposit_amount > 0:
            reservation.deposit_status = "refund_pending"
            reservation.deposit_settlement_status = "refund_pending"
        elif reservation.deposit_status == "pending":
            reservation.deposit_status = "cancelled"
            reservation.deposit_settlement_status = "not_required"

    await db.commit()
    await db.refresh(reservation)
    schedule_reservation_status(str(reservation.id))
    return _out(reservation, restaurant, user)
