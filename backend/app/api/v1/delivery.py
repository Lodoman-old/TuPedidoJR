import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_superuser
from app.db.session import get_db
from app.models.courier_sos import CourierSOS
from app.models.delivery_person import DeliveryPerson
from app.models.delivery_payout import DeliveryPayout
from app.models.cash_advance import CashAdvance
from app.models.order import Order
from app.models.shipment import Shipment
from app.models.user import User
from app.schemas.delivery import (
    AvailabilityUpdate,
    DeliveryEarningsItem,
    DeliveryEarningsOut,
    DeliveryPayoutOut,
    DeliveryPersonAvailable,
    DeliveryPersonAdminUpdate,
    DeliveryPersonOut,
    DeliveryProfileOut,
    DeliveryProfileUpdate,
    LocationUpdate,
    PayoutRequest,
)
from app.schemas.order import AvailableOrderOut, OrderFail, OrderOut
from app.schemas.cash_advance import CashAdvanceCreate, CashAdvanceOut
from app.services.cash_advance_service import create_advance_request
from app.services.courier_limits import active_service_count, ensure_can_accept, service_limits
from app.services.geo_service import find_nearby_delivery_persons
from app.services.loyalty_service import award_on_delivery
from app.services.order_service import get_setting_value
from app.services.order_serialization import order_out
from app.services.push_service import schedule_courier_assigned, schedule_order_status, schedule_arrival, schedule_admin_payout_request, send_to_user
from app.services.email_service import send_email
from app.services.route_service import route_info
from app.services.schedule_service import get_timezone
from app.services.settlement_service import is_order_settleable

router = APIRouter()


def _get_ws_manager():
    from app.main import ws_manager
    return ws_manager


async def _customer_phones(db: AsyncSession, orders: list[Order]) -> dict:
    """Teléfonos de los clientes para el repartidor asignado."""
    ids = {order.user_id for order in orders if order.user_id}
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.phone).where(User.id.in_(ids)))
    return {row.id: row.phone for row in rows}


def _profile_out(dp: DeliveryPerson, user: User) -> DeliveryProfileOut:
    data = DeliveryProfileOut.model_validate(dp)
    data.phone_verified = bool(user.phone_verified)
    return data


def _time_between(moment, start, end) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= moment <= end
    return moment >= start or moment <= end


@router.get("/available", response_model=list[DeliveryPersonAvailable])
async def available_delivery_persons(
    lat: float,
    lng: float,
    radius_m: int = 3000,
    db: AsyncSession = Depends(get_db),
):
    return await find_nearby_delivery_persons(db, lat=lat, lng=lng, radius_m=radius_m)


@router.get("/available-orders", response_model=list[AvailableOrderOut])
async def available_orders(
    lat: float | None = None,
    lng: float | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="No eres repartidor")

    if not dp.is_available:
        return []

    origin_lat, origin_lng = lat, lng
    if origin_lat is None or origin_lng is None:
        loc_result = await db.execute(
            text("""
                SELECT
                    ST_Y(current_location::geometry) AS lat,
                    ST_X(current_location::geometry) AS lng
                FROM delivery_persons WHERE id = :id
            """),
            {"id": dp.id},
        )
        loc = loc_result.mappings().first()
        if loc and loc["lat"] is not None and loc["lng"] is not None:
            origin_lat, origin_lng = float(loc["lat"]), float(loc["lng"])

    result = await db.execute(
        select(Order)
        .where(
            or_(
                Order.status.in_(["awaiting_courier", "ready", "preparing"]),
                and_(
                    Order.requires_courier_approval.is_(True),
                    Order.status.in_(["pending", "confirmed"]),
                ),
            ),
            Order.delivery_person_id.is_(None),
            Order.delivery_mode == "platform",
        )
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )
    orders = list(result.scalars().all())

    restaurants: dict = {}
    if orders:
        resto_ids = list({o.restaurant_id for o in orders})
        resto_result = await db.execute(
            text("""
                SELECT
                    id,
                    name,
                    ST_Y(location::geometry) AS lat,
                    ST_X(location::geometry) AS lng
                FROM restaurants
                WHERE id = ANY(:ids)
            """),
            {"ids": resto_ids},
        )
        restaurants = {row["id"]: row for row in resto_result.mappings().all()}

    items: list[AvailableOrderOut] = []
    for order in orders:
        item = AvailableOrderOut.model_validate(order)
        item.refund_account_holder = None
        item.refund_bank = None
        item.refund_clabe = None
        restaurant = restaurants.get(order.restaurant_id)
        if restaurant:
            item.restaurant_name = restaurant["name"]
            item.restaurant_lat = float(restaurant["lat"]) if restaurant["lat"] is not None else None
            item.restaurant_lng = float(restaurant["lng"]) if restaurant["lng"] is not None else None
            if (
                origin_lat is not None
                and origin_lng is not None
                and item.restaurant_lat is not None
                and item.restaurant_lng is not None
            ):
                distance, duration, _source = await route_info(
                    db,
                    origin_lat,
                    origin_lng,
                    item.restaurant_lat,
                    item.restaurant_lng,
                )
                item.distance_km = round(distance, 2)
                item.eta_min = max(1, math.ceil(duration))
        items.append(item)

    if origin_lat is not None and origin_lng is not None:
        items.sort(key=lambda x: (x.distance_km is None, x.distance_km or 9999))

    return items


@router.post("/accept/{order_id}", response_model=OrderOut)
async def accept_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="No eres repartidor")

    order_result = await db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.delivery_person_id:
        raise HTTPException(status_code=400, detail="Este pedido ya tiene repartidor")
    allowed_statuses = {"awaiting_courier", "ready", "preparing"}
    if order.requires_courier_approval:
        allowed_statuses.update({"pending", "confirmed"})
    if order.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="El pedido no está listo para reparto")
    if order.delivery_mode in ("own", "pickup"):
        detail = (
            "Este pedido es para recoger en el restaurante"
            if order.delivery_mode == "pickup"
            else "Este pedido lo entrega el propio restaurante"
        )
        raise HTTPException(status_code=400, detail=detail)
    if order.requires_courier_approval and order.courier_approval_deadline:
        deadline = order.courier_approval_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > deadline:
            raise HTTPException(
                status_code=400,
                detail="El tiempo para aceptar este pedido ya venció",
            )

    await ensure_can_accept(db, dp)

    approval_flow = order.status == "awaiting_courier"
    order.delivery_person_id = dp.id
    if approval_flow:
        order.status = "preparing"
    # En el flujo normal el estado del pedido lo controla el restaurante
    # (preparando/listo). Aceptar solo asigna al repartidor.
    bonus = dp.delivery_bonus_per_order or Decimal("0")
    if bonus:
        order.delivery_earnings = (order.delivery_earnings or Decimal("0")) + bonus

    peak_enabled = (await get_setting_value(db, "PEAK_BONUS_ENABLED", "false")).lower() == "true"
    if peak_enabled:
        try:
            start = datetime.strptime(
                await get_setting_value(db, "PEAK_BONUS_START", "13:00"), "%H:%M"
            ).time()
            end = datetime.strptime(
                await get_setting_value(db, "PEAK_BONUS_END", "15:00"), "%H:%M"
            ).time()
            tz = await get_timezone(db)
            if _time_between(datetime.now(tz).time(), start, end):
                peak_amount = Decimal(await get_setting_value(db, "PEAK_BONUS_AMOUNT", "5.0"))
                order.delivery_earnings = (order.delivery_earnings or Decimal("0")) + peak_amount
        except (TypeError, ValueError):
            pass

    dp.current_order_id = order.id
    await db.commit()
    await db.refresh(order)
    if approval_flow:
        await _get_ws_manager().notify_order_status(str(order.id), "preparing")
        schedule_order_status(str(order.id), "preparing")
        schedule_courier_assigned(str(order.id))
    else:
        schedule_courier_assigned(str(order.id))
    customer = await db.get(User, order.user_id)
    return order_out(
        order, can_see_refund=False, customer_phone=customer.phone if customer else None
    )


@router.post("/pickup/{order_id}", response_model=OrderOut)
async def pickup_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="No eres repartidor")

    order_result = await db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.delivery_person_id != dp.id:
        raise HTTPException(status_code=400, detail="Este pedido no te pertenece")
    if order.status not in ("ready", "in_delivery"):
        raise HTTPException(
            status_code=400,
            detail="El restaurante todavía no marca el pedido como listo",
        )

    order.status = "picked_up"
    if order.picked_up_at is None:
        order.picked_up_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(order)
    await _get_ws_manager().notify_order_status(str(order.id), "picked_up")
    schedule_order_status(str(order.id), "picked_up")
    customer = await db.get(User, order.user_id)
    return order_out(
        order, can_see_refund=False, customer_phone=customer.phone if customer else None
    )


@router.post("/deliver/{order_id}", response_model=OrderOut)
async def deliver_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="No eres repartidor")

    order_result = await db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.delivery_person_id != dp.id:
        raise HTTPException(status_code=400, detail="Este pedido no te pertenece")
    if order.status != "picked_up":
        raise HTTPException(status_code=400, detail="El pedido no ha sido recogido")

    order.status = "delivered"
    if order.delivered_at is None:
        order.delivered_at = datetime.now(timezone.utc)
    remaining_order_id = await db.scalar(
        select(Order.id)
        .where(
            Order.delivery_person_id == dp.id,
            Order.id != order.id,
            Order.status.notin_(("delivered", "cancelled")),
        )
        .order_by(Order.created_at.desc())
    )
    dp.current_order_id = remaining_order_id
    if order.payment_method == "cash":
        de = order.delivery_earnings or Decimal("0")
        debt = (
            (order.total or Decimal("0"))
            + (order.recharge_total or Decimal("0"))
            - de
        )
        if debt > Decimal("0"):
            dp.pending_platform_debt = (dp.pending_platform_debt or Decimal("0")) + debt
    from app.services import recarga_service

    await recarga_service.attach_courier(db, order, dp.id)
    dp.total_deliveries = (dp.total_deliveries or 0) + 1
    from app.services.payout_service import credit_courier_for_order
    await credit_courier_for_order(db, order)
    from app.services.cash_advance_service import settle_restaurant_advances_for_order
    await settle_restaurant_advances_for_order(db, order)
    await award_on_delivery(db, order)
    await db.commit()
    await db.refresh(order)
    await _get_ws_manager().notify_order_status(str(order.id), "delivered")
    schedule_order_status(str(order.id), "delivered")
    customer = await db.get(User, order.user_id)
    return order_out(
        order, can_see_refund=False, customer_phone=customer.phone if customer else None
    )


@router.post("/orders/{order_id}/fail", response_model=OrderOut)
async def fail_order(
    order_id: str,
    body: OrderFail,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    result = await db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.delivery_person_id != dp.id:
        raise HTTPException(status_code=403, detail="Este pedido no te pertenece")
    if order.status not in ("in_delivery", "picked_up"):
        raise HTTPException(status_code=400, detail="El pedido ya no se puede reportar")

    from app.services.incident_service import report_order_failure

    await report_order_failure(
        db, order, dp,
        reason_code=body.reason_code,
        notes=body.notes,
        photo_url=body.photo_url,
        lat=body.lat,
        lng=body.lng,
    )
    await db.commit()
    await db.refresh(order)
    schedule_order_status(str(order.id), "delivery_failed")
    customer = await db.get(User, order.user_id)
    return order_out(
        order, can_see_refund=False, customer_phone=customer.phone if customer else None
    )


@router.patch("/location", status_code=status.HTTP_204_NO_CONTENT)
async def update_location(
    body: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp_result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = dp_result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="No eres repartidor")

    wkt = f"SRID=4326;POINT({body.lng} {body.lat})"
    await db.execute(
        update(DeliveryPerson)
        .where(DeliveryPerson.id == dp.id)
        .values(current_location=wkt)
    )
    await db.commit()

    # Aviso automático cuando el repartidor llega cerca del cliente.
    active_orders = await db.execute(
        select(Order).where(
            Order.delivery_person_id == dp.id,
            Order.status.in_(["in_delivery", "picked_up"]),
            Order.arrival_notified.is_(False),
        )
    )
    for order in active_orders.scalars().all():
        distance = await db.scalar(
            text(
                "SELECT ST_Distance(o.delivery_location::geography, "
                "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) "
                "FROM orders o WHERE o.id = :oid"
            ),
            {"lng": body.lng, "lat": body.lat, "oid": order.id},
        )
        if distance is not None and float(distance) <= 150:
            order.arrival_notified = True
            await db.commit()
            schedule_arrival(str(order.id))


async def _get_dp(current_user, db):
    result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
    )
    dp = result.scalar_one_or_none()
    if not dp:
        raise HTTPException(status_code=403, detail="No eres repartidor")
    return dp


@router.patch("/persons/{dp_id}", response_model=DeliveryProfileOut)
async def update_delivery_person_admin(
    dp_id: str,
    body: DeliveryPersonAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    dp = await db.get(DeliveryPerson, dp_id)
    if not dp:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    if body.delivery_bonus_per_order is not None:
        dp.delivery_bonus_per_order = body.delivery_bonus_per_order
    if body.payout_frequency_days is not None:
        dp.payout_frequency_days = body.payout_frequency_days
    if body.payout_method is not None:
        dp.payout_method = body.payout_method
    await db.commit()
    await db.refresh(dp)
    user = await db.get(User, dp.user_id)
    return _profile_out(dp, user) if user else dp


@router.post("/advances", response_model=CashAdvanceOut, status_code=status.HTTP_201_CREATED)
async def request_cash_advance(
    body: CashAdvanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    result = await db.execute(select(Order).where(Order.id == body.order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    try:
        return await create_advance_request(db, dp, order, body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/advances", response_model=list[CashAdvanceOut])
async def list_cash_advances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    result = await db.execute(
        select(CashAdvance)
        .where(CashAdvance.delivery_person_id == dp.id)
        .order_by(CashAdvance.created_at.desc())
    )
    return result.scalars().all()


@router.get("/limits")
async def delivery_limits(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    max_services, warn_services = await service_limits(db)
    active = await active_service_count(db, dp.id)
    return {
        "active": active,
        "max": max_services,
        "warn": warn_services,
        "can_accept": active < max_services,
    }


@router.get("/profile", response_model=DeliveryProfileOut)
async def delivery_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    return _profile_out(dp, current_user)


@router.patch("/availability", response_model=DeliveryProfileOut)
async def set_availability(
    body: AvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    dp.is_available = body.is_available
    await db.commit()
    await db.refresh(dp)
    return _profile_out(dp, current_user)


@router.patch("/profile", response_model=DeliveryProfileOut)
async def update_delivery_profile(
    body: DeliveryProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    if body.payout_method is not None:
        dp.payout_method = body.payout_method
    if body.payout_frequency_days is not None:
        dp.payout_frequency_days = body.payout_frequency_days
    if body.bank_name is not None:
        dp.bank_name = body.bank_name
    if body.bank_account_holder is not None:
        dp.bank_account_holder = body.bank_account_holder
    if body.bank_clabe is not None:
        dp.bank_clabe = body.bank_clabe
    await db.commit()
    await db.refresh(dp)
    return _profile_out(dp, current_user)


@router.get("/orders", response_model=list[OrderOut])
async def delivery_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    result = await db.execute(
        select(Order)
        .where(Order.delivery_person_id == dp.id)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )
    orders = list(result.scalars().all())
    phones = await _customer_phones(db, orders)
    return [
        order_out(order, can_see_refund=False, customer_phone=phones.get(order.user_id))
        for order in orders
    ]


@router.get("/payouts", response_model=list[DeliveryPayoutOut])
async def delivery_payouts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    result = await db.execute(
        select(DeliveryPayout)
        .where(DeliveryPayout.delivery_person_id == dp.id)
        .order_by(DeliveryPayout.period_start.desc())
    )
    return result.scalars().all()


@router.get("/earnings", response_model=DeliveryEarningsOut)
async def get_delivery_earnings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    result = await db.execute(
        select(Order)
        .where(Order.delivery_person_id == dp.id, Order.status == "delivered")
    )
    orders = result.scalars().all()

    items = []
    total_earned = Decimal("0")
    total_transfer_earnings = Decimal("0")
    total_cash_collected = Decimal("0")
    total_pending_confirmation = Decimal("0")

    for o in orders:
        de = o.delivery_earnings or Decimal("0")
        item = DeliveryEarningsItem(
            id=o.id,
            placed_at=o.placed_at,
            total=o.total,
            delivery_earnings=de,
            status=o.status,
            payment_method=o.payment_method,
        )
        items.append(item)
        total_earned += de
        if o.payment_method in ("transfer", "mp"):
            if is_order_settleable(o):
                total_transfer_earnings += de
            else:
                total_pending_confirmation += de
        elif o.payment_method == "cash":
            total_cash_collected += o.total or Decimal("0")

    shipments_result = await db.execute(
        select(Shipment).where(
            Shipment.delivery_person_id == dp.id,
            Shipment.status.in_(("delivered", "failed")),
        )
    )
    shipments = shipments_result.scalars().all()
    for s in shipments:
        earning = s.courier_earnings or Decimal("0")
        has_cod = (s.amount_to_collect or 0) > 0
        platform_paid = s.status == "failed" or not has_cod
        items.append(DeliveryEarningsItem(
            id=s.id,
            placed_at=s.created_at,
            total=s.amount_to_collect or Decimal("0"),
            delivery_earnings=earning,
            status=s.status,
            payment_method=(
                "failed" if s.status == "failed"
                else ("cash" if (has_cod and s.status == "delivered") else "transfer")
            ),
        ))
        total_earned += earning
        if platform_paid:
            total_transfer_earnings += earning
        elif s.status == "delivered":
            total_cash_collected += s.amount_to_collect or Decimal("0")

    payouts_result = await db.execute(
        select(DeliveryPayout).where(
            DeliveryPayout.delivery_person_id == dp.id,
            DeliveryPayout.status != "cancelled",
        )
    )
    payouts = list(payouts_result.scalars().all())
    total_paid = sum(
        (p.net_amount or Decimal("0"))
        for p in payouts
        if p.direction == "to_courier" and p.status == "paid"
    )
    total_pending_payouts = sum(
        (p.net_amount or Decimal("0"))
        for p in payouts
        if p.direction == "to_courier" and p.status == "pending"
    )
    pending_debt = dp.pending_platform_debt or Decimal("0")
    pending_credit = dp.pending_platform_credit or Decimal("0")
    from app.services.cash_advance_service import advance_debt
    advance_owed = await advance_debt(db, dp)
    total_net = pending_credit - pending_debt - advance_owed

    return DeliveryEarningsOut(
        total_deliveries=dp.total_deliveries or (len(orders) + len(shipments)),
        total_earned=total_earned,
        total_transfer_earnings=total_transfer_earnings,
        total_cash_collected=total_cash_collected,
        total_paid=total_paid,
        total_pending_payouts=total_pending_payouts,
        total_pending_debt=pending_debt,
        total_pending_from_platform=pending_credit,
        total_pending_confirmation=total_pending_confirmation,
        total_advance_debt=advance_owed,
        total_net=total_net,
        total_pending_earnings=pending_credit,
        orders=items,
    )


@router.post("/request-payout", response_model=DeliveryPayoutOut)
async def request_payout(
    body: PayoutRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    from app.services.payout_service import create_courier_payout

    try:
        payout = await create_courier_payout(
            db, dp, payout_method=body.payout_method if body else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    schedule_admin_payout_request(
        "courier",
        current_user.name or current_user.email,
        abs(payout.net_amount or 0),
        payout.direction,
    )
    return payout

class SOSIn(BaseModel):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    message: str | None = Field(default=None, max_length=500)
    order_id: UUID | None = None


@router.get("/hot-zones")
async def hot_zones(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Zonas con más pedidos entregados y horas pico para el repartidor."""
    await _get_dp(current_user, db)
    span = max(1, min(int(days or 7), 30))
    since = datetime.now(timezone.utc) - timedelta(days=span)

    zones = (
        await db.execute(
            text(
                """
                SELECT c.nombre AS zone,
                       count(*) AS orders,
                       coalesce(round(avg(o.delivery_fee)::numeric, 2), 0) AS avg_fee,
                       round(ST_Y(ST_Centroid(c.geom))::numeric, 6) AS lat,
                       round(ST_X(ST_Centroid(c.geom))::numeric, 6) AS lng
                FROM orders o
                JOIN colonia_areas c ON ST_Contains(c.geom, o.delivery_location::geometry)
                WHERE o.status = 'delivered'
                  AND o.delivery_location IS NOT NULL
                  AND COALESCE(o.delivered_at, o.placed_at) >= :since
                GROUP BY c.nombre, c.geom
                ORDER BY orders DESC
                LIMIT 8
                """
            ),
            {"since": since},
        )
    ).mappings().all()

    peaks = (
        await db.execute(
            text(
                """
                SELECT EXTRACT(HOUR FROM COALESCE(delivered_at, placed_at)
                               AT TIME ZONE 'America/Mexico_City') AS hour,
                       count(*) AS orders
                FROM orders
                WHERE status = 'delivered'
                  AND COALESCE(delivered_at, placed_at) >= :since
                GROUP BY hour
                ORDER BY orders DESC
                LIMIT 4
                """
            ),
            {"since": since},
        )
    ).mappings().all()

    return {
        "days": span,
        "zones": [
            {
                "name": row["zone"],
                "orders": int(row["orders"]),
                "avg_fee": float(row["avg_fee"] or 0),
                "lat": float(row["lat"]) if row["lat"] is not None else None,
                "lng": float(row["lng"]) if row["lng"] is not None else None,
            }
            for row in zones
        ],
        "peak_hours": [
            {"hour": int(row["hour"]), "orders": int(row["orders"])}
            for row in peaks
            if row["hour"] is not None
        ],
    }


@router.post("/sos")
async def send_sos(
    body: SOSIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aviso de auxilio del repartidor a los administradores."""
    from html import escape

    dp = await _get_dp(current_user, db)
    sos = CourierSOS(
        courier_id=dp.id,
        user_id=current_user.id,
        order_id=body.order_id,
        lat=body.lat,
        lng=body.lng,
        message=(body.message or "").strip() or None,
    )
    db.add(sos)
    await db.flush()

    admins = (
        await db.execute(
            select(User).where(User.is_superuser.is_(True), User.is_active.is_(True))
        )
    ).scalars().all()
    maps = (
        f"https://www.google.com/maps/search/?api=1&query={body.lat},{body.lng}"
        if body.lat is not None and body.lng is not None
        else None
    )
    detail = f"{current_user.name or current_user.email} pidió auxilio."
    if body.message:
        detail += f" Mensaje: {body.message}"

    for admin in admins:
        await send_to_user(
            db,
            admin.id,
            "🚨 Auxilio de repartidor",
            detail,
            {"type": "courier_sos", "sos_id": str(sos.id)},
            "red",
        )
        if admin.email:
            html = f"""
            <div style="font-family:Arial,sans-serif;background:#fff5f5;padding:24px">
              <div style="max-width:620px;margin:auto;background:#fff;border-radius:14px;overflow:hidden;border:2px solid #b02a37">
                <div style="background:#b02a37;color:#fff;padding:20px 26px">
                  <h1 style="margin:0;font-size:21px">🚨 Auxilio de repartidor</h1>
                </div>
                <div style="padding:26px;color:#243447;line-height:1.55">
                  <p><strong>{escape(current_user.name or current_user.email)}</strong> pidió auxilio desde la app.</p>
                  <p><strong>Teléfono:</strong> {escape(current_user.phone or 'No registrado')}<br>
                  <strong>Mensaje:</strong> {escape(body.message or 'Sin mensaje')}<br>
                  <strong>Pedido:</strong> {escape(str(body.order_id) if body.order_id else 'Sin pedido activo')}</p>
                  {f'<p><a href="{maps}" style="color:#b02a37">Ver ubicación en Google Maps</a></p>' if maps else ''}
                  <p style="margin-top:20px">Atiende el aviso desde el panel de seguridad.</p>
                </div>
              </div>
            </div>
            """
            await send_email(
                db,
                admin.email,
                "🚨 Auxilio de repartidor",
                html,
                detail,
            )

    await db.commit()
    return {"ok": True, "sos_id": str(sos.id)}
