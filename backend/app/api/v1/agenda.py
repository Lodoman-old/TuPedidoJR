import calendar
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user
from app.db.session import get_db
from app.models.appointment import Appointment
from app.models.business_service import BusinessService
from app.models.business_staff import BusinessStaff
from app.models.restaurant import Restaurant
from app.models.restaurant_schedule import RestaurantSchedule
from app.models.user import User
from app.schemas.agenda import (
    AppointmentIn,
    AppointmentOut,
    AppointmentStatusUpdate,
    ServiceIn,
    ServiceOut,
    ServiceUpdate,
    StaffIn,
    StaffOut,
    StaffUpdate,
)
from app.services.order_service import get_setting_value
from app.services.restaurant_access import MANAGE_ROLES, have_role

router = APIRouter()
LOCAL_TZ = ZoneInfo("America/Mexico_City")
SLOT_STEP = 15
ACTIVE_STATUSES = ("pending", "confirmed")


def _today() -> date:
    return datetime.now(LOCAL_TZ).date()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(timezone.utc)


def _service_out(item: BusinessService) -> ServiceOut:
    return ServiceOut(
        id=item.id, name=item.name, description=item.description,
        duration_min=item.duration_min, price=item.price,
        is_active=item.is_active, sort_order=item.sort_order,
    )


def _staff_out(item: BusinessStaff) -> StaffOut:
    return StaffOut(
        id=item.id, name=item.name, role=item.role,
        is_active=item.is_active, sort_order=item.sort_order,
    )


async def _restaurant(db: AsyncSession, restaurant_id: str) -> Restaurant:
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    return restaurant


async def _manage(db: AsyncSession, restaurant: Restaurant, user: User) -> None:
    if not await have_role(db, restaurant.id, user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No puedes administrar este negocio")


def _agenda_active(restaurant: Restaurant) -> bool:
    if not restaurant.appointments_enabled:
        return False
    if not restaurant.affiliation_expires_at:
        return False
    return restaurant.affiliation_expires_at >= _today()


async def _schedule(db: AsyncSession, restaurant_id) -> list[RestaurantSchedule]:
    result = await db.execute(
        select(RestaurantSchedule).where(RestaurantSchedule.restaurant_id == restaurant_id)
    )
    return list(result.scalars().all())


async def _services(db: AsyncSession, restaurant_id, only_active: bool = False) -> list[BusinessService]:
    query = select(BusinessService).where(BusinessService.restaurant_id == restaurant_id)
    if only_active:
        query = query.where(BusinessService.is_active.is_(True))
    query = query.order_by(BusinessService.sort_order, BusinessService.name)
    return list((await db.execute(query)).scalars().all())


async def _staff(db: AsyncSession, restaurant_id, only_active: bool = False) -> list[BusinessStaff]:
    query = select(BusinessStaff).where(BusinessStaff.restaurant_id == restaurant_id)
    if only_active:
        query = query.where(BusinessStaff.is_active.is_(True))
    query = query.order_by(BusinessStaff.sort_order, BusinessStaff.name)
    return list((await db.execute(query)).scalars().all())


async def _day_appointments(db: AsyncSession, restaurant_id, target: date) -> list[Appointment]:
    start = datetime.combine(target, time(0, 0), tzinfo=LOCAL_TZ)
    end = start + timedelta(days=1)
    result = await db.execute(
        select(Appointment).where(
            Appointment.restaurant_id == restaurant_id,
            Appointment.start_at >= start.astimezone(timezone.utc),
            Appointment.start_at < end.astimezone(timezone.utc),
        )
    )
    return list(result.scalars().all())


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and a_end > b_start


def _day_slots(
    target: date,
    duration_min: int,
    schedule: list[RestaurantSchedule],
    staff: list[BusinessStaff],
    appointments: list[Appointment],
    staff_id=None,
) -> list[datetime]:
    weekday = target.weekday()
    rows = [r for r in schedule if r.day_of_week == weekday and not r.is_closed]
    if not rows or not staff:
        return []
    selected_staff = [s for s in staff if not staff_id or s.id == staff_id]
    if not selected_staff:
        return []
    now = datetime.now(LOCAL_TZ)
    slots = []
    busy = [
        (a.staff_id, a.start_at, a.end_at)
        for a in appointments if a.status in ACTIVE_STATUSES
    ]
    for row in rows:
        open_at = datetime.combine(target, row.open_time, tzinfo=LOCAL_TZ)
        close_at = datetime.combine(target, row.close_time, tzinfo=LOCAL_TZ)
        if close_at <= open_at:
            continue
        candidate = open_at
        while candidate + timedelta(minutes=duration_min) <= close_at:
            end = candidate + timedelta(minutes=duration_min)
            if candidate > now:
                if staff_id:
                    free = not any(
                        sid == staff_id and _overlaps(candidate, end, s, e)
                        for sid, s, e in busy
                    )
                    if free:
                        slots.append(candidate)
                else:
                    for person in selected_staff:
                        if not any(
                            sid == person.id and _overlaps(candidate, end, s, e)
                            for sid, s, e in busy
                        ):
                            slots.append(candidate)
                            break
            candidate += timedelta(minutes=SLOT_STEP)
    return slots


def _parse_local_start(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Horario inválido") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


@router.get("/{restaurant_id}/info")
async def agenda_info(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    _: User | None = Depends(get_optional_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    services = await _services(db, restaurant.id, only_active=True)
    staff = await _staff(db, restaurant.id, only_active=True)
    schedule = await _schedule(db, restaurant.id)
    affiliation_active = (
        restaurant.affiliation_expires_at is not None
        and restaurant.affiliation_expires_at >= _today()
    )
    return {
        "restaurant": {
            "id": str(restaurant.id),
            "name": restaurant.name,
            "slug": restaurant.slug,
            "appointments_enabled": restaurant.appointments_enabled,
            "affiliation_active": affiliation_active,
            "booking_active": _agenda_active(restaurant),
            "schedule_configured": any(not r.is_closed for r in schedule),
        },
        "services": [_service_out(s) for s in services],
        "staff": [_staff_out(s) for s in staff],
        "schedule": [
            {
                "day_of_week": r.day_of_week,
                "open_time": r.open_time.strftime("%H:%M"),
                "close_time": r.close_time.strftime("%H:%M"),
                "is_closed": r.is_closed,
            }
            for r in schedule
        ],
    }


@router.get("/{restaurant_id}/availability")
async def agenda_month(
    restaurant_id: str,
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    service_id: str | None = None,
    staff_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User | None = Depends(get_optional_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    if not _agenda_active(restaurant):
        return {"active": False, "days": []}
    services = await _services(db, restaurant.id, only_active=True)
    service = next((s for s in services if str(s.id) == str(service_id)), None) if service_id else (services[0] if services else None)
    if not service:
        return {"active": True, "days": []}
    staff = await _staff(db, restaurant.id, only_active=True)
    schedule = await _schedule(db, restaurant.id)

    year, month_num = (int(part) for part in month.split("-"))
    days_in_month = calendar.monthrange(year, month_num)[1]
    days = []
    for day_num in range(1, days_in_month + 1):
        target = date(year, month_num, day_num)
        appointments = await _day_appointments(db, restaurant.id, target)
        slots = _day_slots(target, service.duration_min, schedule, staff, appointments, staff_id)
        if slots:
            days.append({"date": target.isoformat(), "count": len(slots)})
    return {"active": True, "service_id": str(service.id), "days": days}


@router.get("/{restaurant_id}/slots")
async def agenda_day(
    restaurant_id: str,
    date_str: str = Query(alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    service_id: str | None = None,
    staff_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User | None = Depends(get_optional_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    if not _agenda_active(restaurant):
        raise HTTPException(status_code=400, detail="Este negocio no tiene agenda activa")
    services = await _services(db, restaurant.id, only_active=True)
    service = next((s for s in services if str(s.id) == str(service_id)), None) if service_id else None
    if not service:
        raise HTTPException(status_code=400, detail="Elige un servicio")
    staff = await _staff(db, restaurant.id, only_active=True)
    schedule = await _schedule(db, restaurant.id)
    target = date.fromisoformat(date_str)
    appointments = await _day_appointments(db, restaurant.id, target)
    slots = _day_slots(target, service.duration_min, schedule, staff, appointments, staff_id)
    return {
        "date": target.isoformat(),
        "duration_min": service.duration_min,
        "slots": [slot.strftime("%H:%M") for slot in slots],
    }


@router.post("/{restaurant_id}/appointments", response_model=AppointmentOut, status_code=201)
async def create_appointment(
    restaurant_id: str,
    body: AppointmentIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    if not _agenda_active(restaurant):
        raise HTTPException(status_code=400, detail="Este negocio no tiene agenda activa")
    services = await _services(db, restaurant.id, only_active=True)
    service = next((s for s in services if str(s.id) == str(body.service_id)), None)
    if not service:
        raise HTTPException(status_code=400, detail="Servicio no disponible")
    staff_list = await _staff(db, restaurant.id, only_active=True)
    if body.staff_id:
        staff = next((s for s in staff_list if str(s.id) == str(body.staff_id)), None)
        if not staff:
            raise HTTPException(status_code=400, detail="Profesional no disponible")
    else:
        staff = None

    start_local = _parse_local_start(body.start_at)
    if start_local.date() < _today():
        raise HTTPException(status_code=400, detail="Esa fecha ya pasó")
    if start_local.minute % SLOT_STEP != 0 or start_local.second != 0:
        raise HTTPException(status_code=400, detail="Elige un horario válido")
    end_local = start_local + timedelta(minutes=service.duration_min)
    schedule = await _schedule(db, restaurant.id)
    rows = [r for r in schedule if r.day_of_week == start_local.weekday() and not r.is_closed]
    if not rows:
        raise HTTPException(status_code=400, detail="El negocio no abre ese día")
    inside = any(
        start_local.time() >= r.open_time and end_local.time() <= r.close_time
        for r in rows
    )
    if not inside:
        raise HTTPException(status_code=400, detail="Ese horario está fuera del horario del negocio")

    # Serializa las reservas del negocio para evitar dos citas al mismo tiempo.
    await db.execute(
        select(Restaurant.id).where(Restaurant.id == restaurant.id).with_for_update()
    )

    appointments = await _day_appointments(db, restaurant.id, start_local.date())
    free_staff = []
    for person in ([staff] if staff else staff_list):
        busy = any(
            a.staff_id == person.id and _overlaps(start_local, end_local, a.start_at, a.end_at)
            for a in appointments if a.status in ACTIVE_STATUSES
        )
        if not busy:
            free_staff.append(person)
    if not free_staff:
        raise HTTPException(status_code=409, detail="Ese horario ya no está disponible")
    chosen = free_staff[0]

    client_fee = Decimal(await get_setting_value(db, "APP_APPOINTMENT_CLIENT_FEE", "5.0"))
    business_fee = Decimal(await get_setting_value(db, "APP_APPOINTMENT_BUSINESS_FEE", "5.0"))
    appointment = Appointment(
        restaurant_id=restaurant.id,
        service_id=service.id,
        staff_id=chosen.id,
        client_user_id=current_user.id,
        client_name=body.client_name.strip(),
        client_phone=(body.client_phone or "").strip() or None,
        start_at=_utc(start_local),
        end_at=_utc(end_local),
        status="confirmed",
        price=service.price,
        payment_mode="cash",
        payment_status="cash_pending",
        deposit_amount=Decimal("0"),
        platform_fee=client_fee + business_fee,
        business_fee=business_fee,
        notes=(body.notes or "").strip() or None,
    )
    db.add(appointment)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ese horario ya no está disponible") from exc
    await db.refresh(appointment)
    return AppointmentOut(
        id=appointment.id,
        service_id=appointment.service_id,
        staff_id=appointment.staff_id,
        service_name=service.name,
        staff_name=chosen.name,
        client_name=appointment.client_name,
        client_phone=appointment.client_phone,
        start_at=appointment.start_at,
        end_at=appointment.end_at,
        status=appointment.status,
        price=appointment.price,
        payment_mode=appointment.payment_mode,
        payment_status=appointment.payment_status,
        platform_fee=appointment.platform_fee,
        business_fee=appointment.business_fee,
        notes=appointment.notes,
    )


@router.get("/{restaurant_id}/appointments", response_model=list[AppointmentOut])
async def list_appointments(
    restaurant_id: str,
    date_str: str | None = Query(default=None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    target = date.fromisoformat(date_str) if date_str else _today()
    rows = await _day_appointments(db, restaurant.id, target)
    services = {str(s.id): s.name for s in await _services(db, restaurant.id)}
    staff = {str(s.id): s.name for s in await _staff(db, restaurant.id)}
    return [
        AppointmentOut(
            id=a.id,
            service_id=a.service_id,
            staff_id=a.staff_id,
            service_name=services.get(str(a.service_id)),
            staff_name=staff.get(str(a.staff_id)),
            client_name=a.client_name,
            client_phone=a.client_phone,
            start_at=a.start_at,
            end_at=a.end_at,
            status=a.status,
            price=a.price,
            payment_mode=a.payment_mode,
            payment_status=a.payment_status,
            platform_fee=a.platform_fee,
            business_fee=a.business_fee,
            notes=a.notes,
        )
        for a in sorted(rows, key=lambda x: x.start_at)
    ]


@router.patch("/{restaurant_id}/appointments/{appointment_id}", response_model=AppointmentOut)
async def update_appointment(
    restaurant_id: str,
    appointment_id: str,
    body: AppointmentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Cita no encontrada")
    appointment.status = body.status
    await db.commit()
    await db.refresh(appointment)
    services = {str(s.id): s.name for s in await _services(db, restaurant.id)}
    staff = {str(s.id): s.name for s in await _staff(db, restaurant.id)}
    return AppointmentOut(
        id=appointment.id,
        service_id=appointment.service_id,
        staff_id=appointment.staff_id,
        service_name=services.get(str(appointment.service_id)),
        staff_name=staff.get(str(appointment.staff_id)),
        client_name=appointment.client_name,
        client_phone=appointment.client_phone,
        start_at=appointment.start_at,
        end_at=appointment.end_at,
        status=appointment.status,
        price=appointment.price,
        payment_mode=appointment.payment_mode,
        payment_status=appointment.payment_status,
        platform_fee=appointment.platform_fee,
        business_fee=appointment.business_fee,
        notes=appointment.notes,
    )


@router.get("/{restaurant_id}/services", response_model=list[ServiceOut])
async def list_services(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    return [_service_out(s) for s in await _services(db, restaurant.id)]


@router.post("/{restaurant_id}/services", response_model=ServiceOut, status_code=201)
async def create_service(
    restaurant_id: str,
    body: ServiceIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    service = BusinessService(restaurant_id=restaurant.id, **body.model_dump())
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return _service_out(service)


@router.patch("/{restaurant_id}/services/{service_id}", response_model=ServiceOut)
async def update_service(
    restaurant_id: str,
    service_id: str,
    body: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    service = await db.get(BusinessService, service_id)
    if not service or service.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(service, key, value)
    await db.commit()
    await db.refresh(service)
    return _service_out(service)


@router.delete("/{restaurant_id}/services/{service_id}", status_code=204)
async def delete_service(
    restaurant_id: str,
    service_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    service = await db.get(BusinessService, service_id)
    if not service or service.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    service.is_active = False
    await db.commit()


@router.get("/{restaurant_id}/staff", response_model=list[StaffOut])
async def list_staff(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    return [_staff_out(s) for s in await _staff(db, restaurant.id)]


@router.post("/{restaurant_id}/staff", response_model=StaffOut, status_code=201)
async def create_staff(
    restaurant_id: str,
    body: StaffIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    staff = BusinessStaff(restaurant_id=restaurant.id, **body.model_dump())
    db.add(staff)
    await db.commit()
    await db.refresh(staff)
    return _staff_out(staff)


@router.patch("/{restaurant_id}/staff/{staff_id}", response_model=StaffOut)
async def update_staff(
    restaurant_id: str,
    staff_id: str,
    body: StaffUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    staff = await db.get(BusinessStaff, staff_id)
    if not staff or staff.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Profesional no encontrado")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(staff, key, value)
    await db.commit()
    await db.refresh(staff)
    return _staff_out(staff)


@router.delete("/{restaurant_id}/staff/{staff_id}", status_code=204)
async def delete_staff(
    restaurant_id: str,
    staff_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    staff = await db.get(BusinessStaff, staff_id)
    if not staff or staff.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Profesional no encontrado")
    staff.is_active = False
    await db.commit()


@router.patch("/{restaurant_id}/settings")
async def update_agenda_settings(
    restaurant_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    restaurant = await _restaurant(db, restaurant_id)
    await _manage(db, restaurant, current_user)
    if "appointments_enabled" in body:
        restaurant.appointments_enabled = bool(body["appointments_enabled"])
    await db.commit()
    return {"appointments_enabled": bool(restaurant.appointments_enabled)}
