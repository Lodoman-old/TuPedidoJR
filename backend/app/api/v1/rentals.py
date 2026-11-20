import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user
from app.db.session import get_db
from app.models.business_service import BusinessService
from app.models.business_ledger import BusinessLedger
from app.models.rental_booking import RentalBooking, RentalBookingItem
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.rental import (
    RentalBookingIn,
    RentalBookingOut,
    RentalItemIn,
    RentalItemOut,
    RentalItemUpdate,
    RentalStatusUpdate,
)
from app.services.appointment_payment_service import payment_plan
from app.services.order_service import get_setting_value
from app.services.rental_payment_service import schedule_rental_validation
from app.services.push_service import schedule_new_rental
from app.services.restaurant_access import MANAGE_ROLES, have_role

router = APIRouter()
LOCAL_TZ = ZoneInfo("America/Mexico_City")
SLOT_STEP_MIN = 30
OPEN_HOUR = 8
CLOSE_HOUR = 22
ACTIVE_STATUSES = ("pending", "confirmed")


def _today() -> date:
    return datetime.now(LOCAL_TZ).date()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(timezone.utc)


def _parse_local(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Horario inválido") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


async def _restaurant(db: AsyncSession, restaurant_id: str) -> Restaurant:
    restaurant = await db.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    return restaurant


async def _manage(db: AsyncSession, restaurant: Restaurant, user: User) -> None:
    if not await have_role(db, restaurant.id, user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No puedes administrar este negocio")


async def _items(db: AsyncSession, restaurant_id, only_active: bool = False) -> list[BusinessService]:
    query = select(BusinessService).where(
        BusinessService.restaurant_id == restaurant_id,
        BusinessService.is_rental.is_(True),
    )
    if only_active:
        query = query.where(BusinessService.is_active.is_(True))
    query = query.order_by(BusinessService.sort_order, BusinessService.name)
    return list((await db.execute(query)).scalars().all())


def _item_out(item: BusinessService) -> RentalItemOut:
    return RentalItemOut(
        id=item.id,
        name=item.name,
        description=item.description,
        duration_min=item.duration_min,
        price=item.price,
        stock=item.stock,
        requires_address=item.requires_address,
        is_active=item.is_active,
        sort_order=item.sort_order,
    )


def _booking_out(booking: RentalBooking, restaurant_name: str | None = None) -> RentalBookingOut:
    return RentalBookingOut(
        id=booking.id,
        restaurant_id=booking.restaurant_id,
        restaurant_name=restaurant_name,
        client_name=booking.client_name,
        client_phone=booking.client_phone,
        start_at=booking.start_at,
        end_at=booking.end_at,
        address=booking.address,
        status=booking.status,
        payment_mode=booking.payment_mode,
        payment_status=booking.payment_status,
        deposit_amount=booking.deposit_amount,
        deposit_percent=booking.deposit_percent,
        online_amount=booking.online_amount,
        cash_due=booking.cash_due,
        business_credit=booking.business_credit,
        business_debt=booking.business_debt,
        platform_fee=booking.platform_fee,
        business_fee=booking.business_fee,
        proof_url=booking.proof_url,
        receipt_status=booking.receipt_status,
        paid_at=booking.paid_at,
        refund_amount=booking.refund_amount,
        notes=booking.notes,
        items=[
            {
                "id": row.id,
                "service_id": row.service_id,
                "name": row.name,
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "duration_min": row.duration_min,
                "start_at": row.start_at,
                "end_at": row.end_at,
                "subtotal": row.subtotal,
            }
            for row in sorted(booking.items, key=lambda x: x.start_at)
        ],
    )


async def _used_quantity(
    db: AsyncSession,
    service_id,
    start_utc: datetime,
    end_utc: datetime,
) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(RentalBookingItem.quantity), 0))
        .join(RentalBooking, RentalBooking.id == RentalBookingItem.booking_id)
        .where(
            RentalBookingItem.service_id == service_id,
            RentalBooking.status.in_(ACTIVE_STATUSES),
            RentalBookingItem.start_at < end_utc,
            RentalBookingItem.end_at > start_utc,
        )
    )
    return int(result.scalar_one() or 0)


async def _has_stock(
    db: AsyncSession,
    item: BusinessService,
    quantity: int,
    start_utc: datetime,
    end_utc: datetime,
) -> bool:
    used = await _used_quantity(db, item.id, start_utc, end_utc)
    return used + quantity <= int(item.stock or 0)


@router.get("/my-bookings", response_model=list[RentalBookingOut])
async def my_rental_bookings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = list((await db.execute(
        select(RentalBooking)
        .where(RentalBooking.client_user_id == current_user.id)
        .order_by(RentalBooking.start_at.desc())
        .limit(100)
    )).scalars().all())
    restaurant_ids = {b.restaurant_id for b in rows}
    names = {
        str(r.id): r.name for r in (await db.execute(
            select(Restaurant).where(Restaurant.id.in_(restaurant_ids))
        )).scalars().all()
    } if restaurant_ids else {}
    return [_booking_out(b, names.get(str(b.restaurant_id))) for b in rows]


@router.get("/{restaurant_id}/info")
async def rental_info(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    _: User | None = Depends(get_optional_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    items = await _items(db, restaurant.id, only_active=True)
    return {
        "restaurant": {
            "id": str(restaurant.id),
            "name": restaurant.name,
            "slug": restaurant.slug,
            "address": restaurant.address,
            "phone": restaurant.phone,
            "business_type": restaurant.business_type,
        },
        "items": [_item_out(item) for item in items],
        "payment": {
            "client_fee": str(await get_setting_value(db, "APP_APPOINTMENT_CLIENT_FEE", "5.0")),
            "business_fee": str(await get_setting_value(db, "APP_APPOINTMENT_BUSINESS_FEE", "5.0")),
            "deposit_percent": str(await get_setting_value(db, "APP_APPOINTMENT_DEPOSIT_PERCENT", "20")),
            "bank_name": (await get_setting_value(db, "BANK_NAME", "")).strip(),
            "bank_holder": (await get_setting_value(db, "BANK_ACCOUNT_HOLDER", "")).strip(),
            "bank_clabe": (await get_setting_value(db, "BANK_CLABE", "")).strip(),
        },
    }


@router.get("/{restaurant_id}/items/{service_id}/slots")
async def rental_slots(
    restaurant_id: str,
    service_id: str,
    date_str: str = Query(alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    quantity: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    restaurant = await _restaurant(db, restaurant_id)
    item = next((row for row in await _items(db, restaurant.id, only_active=True) if str(row.id) == str(service_id)), None)
    if not item:
        raise HTTPException(status_code=404, detail="Artículo no encontrado")
    target = date.fromisoformat(date_str)
    if target < _today():
        raise HTTPException(status_code=400, detail="Esa fecha ya pasó")
    slots = []
    start = datetime.combine(target, time(OPEN_HOUR, 0), tzinfo=LOCAL_TZ)
    close = datetime.combine(target, time(CLOSE_HOUR, 0), tzinfo=LOCAL_TZ)
    candidate = start
    while candidate + timedelta(minutes=item.duration_min) <= close:
        end = candidate + timedelta(minutes=item.duration_min)
        if candidate > datetime.now(LOCAL_TZ):
            if await _has_stock(db, item, quantity, _utc(candidate), _utc(end)):
                slots.append(candidate.strftime("%H:%M"))
        candidate += timedelta(minutes=SLOT_STEP_MIN)
    return {
        "date": target.isoformat(),
        "duration_min": item.duration_min,
        "stock": item.stock,
        "slots": slots,
    }


@router.post("/{restaurant_id}/bookings", response_model=RentalBookingOut, status_code=201)
async def create_rental_booking(
    restaurant_id: str,
    body: RentalBookingIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    items = await _items(db, restaurant.id, only_active=True)
    by_id = {str(item.id): item for item in items}
    seen = set()
    parsed = []
    for line in body.items:
        key = str(line.service_id)
        if key in seen:
            raise HTTPException(status_code=400, detail="No repitas el mismo artículo")
        seen.add(key)
        item = by_id.get(key)
        if not item:
            raise HTTPException(status_code=400, detail="Artículo no disponible")
        start_local = _parse_local(line.start_at)
        if start_local.date() < _today():
            raise HTTPException(status_code=400, detail="Esa fecha ya pasó")
        end_local = start_local + timedelta(minutes=item.duration_min)
        parsed.append((item, int(line.quantity), start_local, end_local))

    needs_address = any(item.requires_address for item, _, _, _ in parsed)
    if needs_address and not (body.address or "").strip():
        raise HTTPException(status_code=400, detail="Indica la dirección donde se entregará la renta")

    if body.payment_mode in ("deposit", "full") and not (body.proof_url or "").strip():
        raise HTTPException(status_code=400, detail="Sube el comprobante de tu transferencia")

    await db.execute(
        select(Restaurant.id).where(Restaurant.id == restaurant.id).with_for_update()
    )
    for item, quantity, start_local, end_local in parsed:
        if quantity > int(item.stock or 0):
            raise HTTPException(status_code=400, detail=f"No hay existencia suficiente de {item.name}")
        if not await _has_stock(db, item, quantity, _utc(start_local), _utc(end_local)):
            raise HTTPException(
                status_code=409,
                detail=f"{item.name} ya no está disponible en ese horario. Elige otro.",
            )

    subtotal = sum((item.price * quantity for item, quantity, _, _ in parsed), Decimal("0"))
    client_fee = Decimal(await get_setting_value(db, "APP_APPOINTMENT_CLIENT_FEE", "5.0"))
    business_fee = Decimal(await get_setting_value(db, "APP_APPOINTMENT_BUSINESS_FEE", "5.0"))
    deposit_percent = Decimal(await get_setting_value(db, "APP_APPOINTMENT_DEPOSIT_PERCENT", "20"))
    plan = payment_plan(subtotal, body.payment_mode, client_fee, business_fee, deposit_percent)

    start_local = min(row[2] for row in parsed)
    end_local = max(row[3] for row in parsed)
    booking = RentalBooking(
        restaurant_id=restaurant.id,
        client_user_id=current_user.id,
        client_name=body.client_name.strip(),
        client_phone=(body.client_phone or "").strip() or None,
        start_at=_utc(start_local),
        end_at=_utc(end_local),
        address=(body.address or "").strip() or None,
        location=(
            f"SRID=4326;POINT({body.lng} {body.lat})"
            if body.lat is not None and body.lng is not None else None
        ),
        status="confirmed",
        payment_mode=body.payment_mode,
        payment_status=plan["payment_status"],
        deposit_amount=plan["deposit_amount"],
        deposit_percent=plan["deposit_percent"],
        online_amount=plan["online_amount"],
        cash_due=plan["cash_due"],
        business_credit=plan["business_credit"],
        business_debt=plan["business_debt"],
        platform_fee=client_fee + business_fee,
        business_fee=business_fee,
        receipt_status="pending" if body.payment_mode != "cash" else "none",
        proof_url=(body.proof_url or "").strip() or None,
        notes=(body.notes or "").strip() or None,
    )
    for item, quantity, item_start, item_end in parsed:
        booking.items.append(RentalBookingItem(
            id=uuid.uuid4(),
            service_id=item.id,
            name=item.name,
            quantity=quantity,
            unit_price=item.price,
            duration_min=item.duration_min,
            start_at=_utc(item_start),
            end_at=_utc(item_end),
            subtotal=(item.price * quantity),
        ))
    db.add(booking)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ese horario ya no está disponible") from exc
    await db.refresh(booking)
    schedule_new_rental(str(booking.id))
    if booking.payment_mode != "cash":
        schedule_rental_validation(str(booking.id))
    return _booking_out(booking, restaurant.name)


@router.get("/{restaurant_id}/bookings", response_model=list[RentalBookingOut])
async def list_rental_bookings(
    restaurant_id: str,
    date_str: str | None = Query(default=None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    target = date.fromisoformat(date_str) if date_str else _today()
    start_local = datetime.combine(target, time(0, 0), tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    rows = list((await db.execute(
        select(RentalBooking).where(
            RentalBooking.restaurant_id == restaurant.id,
            RentalBooking.start_at >= _utc(start_local),
            RentalBooking.start_at < _utc(end_local),
        ).order_by(RentalBooking.start_at)
    )).scalars().all())
    return [_booking_out(row, restaurant.name) for row in rows]


@router.patch("/{restaurant_id}/bookings/{booking_id}", response_model=RentalBookingOut)
async def update_rental_booking(
    restaurant_id: str,
    booking_id: str,
    body: RentalStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    booking = await db.get(RentalBooking, booking_id)
    if not booking or booking.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    if booking.status not in ("pending", "confirmed"):
        raise HTTPException(status_code=400, detail="La reserva ya está cerrada")
    if body.status == "cancelled":
        if booking.payment_mode != "cash" and booking.payment_status in ("paid", "deposit_paid", "proof_review"):
            booking.refund_amount = booking.online_amount
    elif body.status == "completed":
        if booking.payment_mode == "cash":
            db.add(BusinessLedger(
                restaurant_id=restaurant.id,
                rental_booking_id=booking.id,
                kind="debit",
                amount=booking.platform_fee,
                status="pending",
                notes="Comisión de renta cobrada en efectivo",
            ))
        else:
            db.add(BusinessLedger(
                restaurant_id=restaurant.id,
                rental_booking_id=booking.id,
                kind="credit",
                amount=booking.business_credit,
                status="pending",
                notes="Liquidación de renta pagada en línea",
            ))
    booking.status = body.status
    await db.commit()
    await db.refresh(booking)
    return _booking_out(booking, restaurant.name)


@router.get("/{restaurant_id}/items", response_model=list[RentalItemOut])
async def list_rental_items(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    return [_item_out(item) for item in await _items(db, restaurant.id)]


@router.post("/{restaurant_id}/items", response_model=RentalItemOut, status_code=201)
async def create_rental_item(
    restaurant_id: str,
    body: RentalItemIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    item = BusinessService(restaurant_id=restaurant.id, is_rental=True, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _item_out(item)


@router.patch("/{restaurant_id}/items/{item_id}", response_model=RentalItemOut)
async def update_rental_item(
    restaurant_id: str,
    item_id: str,
    body: RentalItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    item = await db.get(BusinessService, item_id)
    if not item or item.restaurant_id != restaurant.id or not item.is_rental:
        raise HTTPException(status_code=404, detail="Artículo no encontrado")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return _item_out(item)
