import math
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_superuser
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.delivery_payout import DeliveryPayout
from app.models.cash_advance import CashAdvance
from app.models.order import Order
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
)
from app.schemas.order import AvailableOrderOut, OrderOut
from app.schemas.cash_advance import CashAdvanceCreate, CashAdvanceOut
from app.services.cash_advance_service import create_advance_request
from app.services.geo_service import find_nearby_delivery_persons
from app.services.loyalty_service import award_on_delivery
from app.services.order_service import get_setting_value
from app.services.order_serialization import order_out
from app.services.push_service import schedule_courier_assigned, schedule_order_status, schedule_arrival
from app.services.route_service import route_info
from app.services.schedule_service import get_timezone
from app.services.settlement_service import is_order_settleable

router = APIRouter()


def _get_ws_manager():
    from app.main import ws_manager
    return ws_manager


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

    approval_flow = order.status == "awaiting_courier"
    reserved_flow = order.requires_courier_approval and order.status in (
        "pending",
        "confirmed",
    )
    order.delivery_person_id = dp.id
    if approval_flow:
        order.status = "preparing"
    elif not reserved_flow:
        order.status = "in_delivery"
    # Apply the courier's individual per-delivery bonus, if configured.
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
    dp.is_available = False
    await db.commit()
    await db.refresh(order)
    if approval_flow:
        await _get_ws_manager().notify_order_status(str(order.id), "preparing")
        schedule_order_status(str(order.id), "preparing")
        schedule_courier_assigned(str(order.id))
    elif reserved_flow:
        schedule_courier_assigned(str(order.id))
    else:
        await _get_ws_manager().notify_order_status(str(order.id), "in_delivery")
        schedule_order_status(str(order.id), "in_delivery")
    return order_out(order, can_see_refund=False)


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
    if order.status != "in_delivery":
        raise HTTPException(status_code=400, detail="El pedido no está en reparto")

    order.status = "picked_up"
    if order.picked_up_at is None:
        order.picked_up_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(order)
    await _get_ws_manager().notify_order_status(str(order.id), "picked_up")
    schedule_order_status(str(order.id), "picked_up")
    return order


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
    dp.current_order_id = None
    dp.is_available = True
    if order.payment_method == "cash":
        de = order.delivery_earnings or Decimal("0")
        debt = (order.total or Decimal("0")) - de
        if debt > Decimal("0"):
            dp.pending_platform_debt = (dp.pending_platform_debt or Decimal("0")) + debt
    from app.services.cash_advance_service import settle_restaurant_advances_for_order
    await settle_restaurant_advances_for_order(db, order)
    await award_on_delivery(db, order)
    await db.commit()
    await db.refresh(order)
    await _get_ws_manager().notify_order_status(str(order.id), "delivered")
    schedule_order_status(str(order.id), "delivered")
    return order


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
    return dp


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


@router.get("/profile", response_model=DeliveryProfileOut)
async def delivery_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_dp(current_user, db)


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
    return dp


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
    return dp


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
    return [order_out(order, can_see_refund=False) for order in result.scalars().all()]


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

    payouts_result = await db.execute(
        select(DeliveryPayout)
        .where(
            DeliveryPayout.delivery_person_id == dp.id,
            DeliveryPayout.status == "paid",
        )
    )
    total_paid = Decimal("0")
    for p in payouts_result.scalars().all():
        total_paid += p.total_earnings

    pending_payouts_result = await db.execute(
        select(DeliveryPayout).where(
            DeliveryPayout.delivery_person_id == dp.id,
            DeliveryPayout.status == "pending",
        )
    )
    total_pending_payouts = sum(
        (p.total_earnings or Decimal("0"))
        for p in pending_payouts_result.scalars().all()
    )

    pending_debt = dp.pending_platform_debt or Decimal("0")
    from app.services.cash_advance_service import advance_debt
    advance_owed = await advance_debt(db, dp)
    pending_from_platform = total_transfer_earnings - total_paid
    if pending_from_platform < Decimal("0"):
        pending_from_platform = Decimal("0")

    return DeliveryEarningsOut(
        total_deliveries=len(orders),
        total_earned=total_earned,
        total_transfer_earnings=total_transfer_earnings,
        total_cash_collected=total_cash_collected,
        total_paid=total_paid,
        total_pending_payouts=total_pending_payouts,
        total_pending_debt=pending_debt,
        total_pending_from_platform=pending_from_platform,
        total_pending_confirmation=total_pending_confirmation,
        total_advance_debt=advance_owed,
        orders=items,
    )


@router.post("/request-payout", response_model=DeliveryPayoutOut)
async def request_payout(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _get_dp(current_user, db)
    from app.services.payout_service import create_courier_payout

    try:
        payout = await create_courier_payout(db, dp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payout
