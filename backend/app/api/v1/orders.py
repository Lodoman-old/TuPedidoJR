from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.constants import OrderStatus
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_item_option import OrderItemOption
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.order import (
    CancelOrderRequest,
    CancellationPolicyOut,
    OrderCreate,
    OrderOut,
    OrderStatusUpdate,
    RefundAccountUpdate,
    TrackingOut,
)
from app.services.cancellation_service import apply_cancellation, can_cancel, get_policy
from app.services.restaurant_access import ORDER_ROLES, have_role
from app.services.estimation_service import calculate_estimated_time
from app.services.order_service import calculate_order_totals, get_approval_timeout_min, get_setting_value, resolve_item_options
from app.services.order_serialization import order_out
from app.services.loyalty_service import apply_redemption, preview_redemption, award_on_delivery
from app.services.push_service import schedule_available_order, schedule_courier_ready, schedule_new_order, schedule_order_status
from app.services.schedule_service import restaurant_open_state
from app.services.tracking_service import build_tracking
from app.ws.manager import ConnectionManager

router = APIRouter()


def _get_ws_manager() -> ConnectionManager:
    from app.main import ws_manager
    return ws_manager


async def _restaurant_coords(db: AsyncSession, restaurant: Restaurant) -> tuple[float, float]:
    result = await db.execute(
        text("""
            SELECT ST_Y(r.location::geometry) AS lat, ST_X(r.location::geometry) AS lng
            FROM restaurants r WHERE r.id = :rid
        """),
        {"rid": restaurant.id},
    )
    row = result.mappings().first()
    if row and row["lat"] is not None and row["lng"] is not None:
        return float(row["lat"]), float(row["lng"])
    return 20.644, -100.993


def _is_pickup(body: OrderCreate) -> bool:
    return body.fulfillment_type == "pickup"


@router.post("/estimate")
async def estimate_time(
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == body.restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
        if restaurant.status != "active" and not current_user.is_superuser:
            raise HTTPException(status_code=409, detail="El restaurante todavía no está activo")
    pickup = _is_pickup(body)
    if pickup and not restaurant.pickup_enabled:
        raise HTTPException(status_code=400, detail="Este restaurante no permite recoger pedidos")
    if not pickup and body.delivery_location is None:
        raise HTTPException(status_code=400, detail="Falta la ubicación de entrega")
    items_data = []
    for item in body.items:
        menu_result = await db.execute(select(MenuItem).where(MenuItem.id == item.menu_item_id))
        menu_item = menu_result.scalar_one_or_none()
        if not menu_item or menu_item.restaurant_id != restaurant.id:
            raise HTTPException(status_code=400, detail=f"Item {item.menu_item_id} no válido")
        try:
            unit_price, selected = await resolve_item_options(db, menu_item, item.option_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items_data.append({
            "menu_item": menu_item, "item": item,
            "unit_price": unit_price, "options": selected,
        })
    lat, lng = await _restaurant_coords(db, restaurant) if pickup else (
        body.delivery_location.lat, body.delivery_location.lng,
    )
    estimated_min = await calculate_estimated_time(
        db, restaurant, items_data, lng, lat, pickup=pickup,
    )
    return {"estimated_delivery_min": estimated_min}


async def _check_max_distance(db: AsyncSession, distance_km, pickup: bool) -> None:
    if pickup or distance_km is None:
        return
    raw = await get_setting_value(db, "DELIVERY_MAX_KM", "12")
    try:
        max_km = float(raw)
    except (TypeError, ValueError):
        max_km = 0.0
    if max_km > 0 and float(distance_km) > max_km:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La dirección está fuera de cobertura: {float(distance_km):.1f} km. "
                f"El máximo es {max_km:.0f} km."
            ),
        )


async def _courier_approval_km(db: AsyncSession) -> float:
    raw = await get_setting_value(db, "DELIVERY_APPROVAL_KM", "8")
    try:
        km = float(raw)
    except (TypeError, ValueError):
        km = 8.0
    return max(km, 0.0)


async def _requires_courier_approval(
    db: AsyncSession,
    restaurant: Restaurant,
    pickup: bool,
    distance_km,
) -> tuple[bool, float]:
    """Los pedidos lejanos se retienen hasta que un repartidor los acepte."""
    threshold = await _courier_approval_km(db)
    if (
        pickup
        or restaurant.delivery_mode != "platform"
        or distance_km is None
        or threshold <= 0
    ):
        return False, threshold
    return float(distance_km) >= threshold, threshold


def _clean_clabe(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


@router.post("/estimate-price")
async def estimate_price(
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == body.restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
        if restaurant.status != "active" and not current_user.is_superuser:
            raise HTTPException(status_code=409, detail="El restaurante todavía no está activo")
    pickup = _is_pickup(body)
    if pickup and not restaurant.pickup_enabled:
        raise HTTPException(status_code=400, detail="Este restaurante no permite recoger pedidos")
    if not pickup and body.delivery_location is None:
        raise HTTPException(status_code=400, detail="Falta la ubicación de entrega")
    items_data = []
    for item in body.items:
        menu_result = await db.execute(select(MenuItem).where(MenuItem.id == item.menu_item_id))
        menu_item = menu_result.scalar_one_or_none()
        if not menu_item or menu_item.restaurant_id != restaurant.id:
            raise HTTPException(status_code=400, detail=f"Item {item.menu_item_id} no válido")
        try:
            unit_price, selected = await resolve_item_options(db, menu_item, item.option_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items_data.append({
            "menu_item": menu_item, "item": item,
            "unit_price": unit_price, "options": selected,
        })
    lat, lng = await _restaurant_coords(db, restaurant) if pickup else (
        body.delivery_location.lat, body.delivery_location.lng,
    )
    subtotal, delivery_fee, discount, total, coupon, platform_commission, flat_usage_fee, delivery_earnings, distance_km = await calculate_order_totals(
        db, restaurant, items_data, body.coupon_code,
        delivery_lat=lat, delivery_lng=lng,
        tip_amount=Decimal("0") if pickup else body.tip_amount,
        pickup=pickup,
    )
    await _check_max_distance(db, distance_km, pickup)
    pre_subtotal = sum(
        (entry["unit_price"] * entry["item"].quantity for entry in items_data),
        Decimal("0"),
    )
    points_redeemed, loyalty_discount = await preview_redemption(
        db, current_user, body.points_to_redeem,
        max(pre_subtotal - discount, Decimal("0")),
    )
    if loyalty_discount:
        total = max(total - loyalty_discount, Decimal("0"))

    warn_raw = await get_setting_value(db, "DELIVERY_WARN_KM", "8")
    try:
        warn_km = float(warn_raw)
    except (TypeError, ValueError):
        warn_km = 8.0
    requires_approval, approval_km = await _requires_courier_approval(
        db, restaurant, pickup, distance_km
    )
    approval_timeout_min = await get_approval_timeout_min(db)
    distance_warning = None
    if requires_approval:
        timeout_text = (
            f" Si ningún repartidor lo acepta en {approval_timeout_min} minutos, "
            "el pedido se cancela automáticamente y se te devuelve el dinero."
            if approval_timeout_min > 0
            else ""
        )
        distance_warning = (
            f"Tu pedido está a {float(distance_km):.1f} km del restaurante. "
            "Primero un repartidor debe aceptarlo y, hasta entonces, el restaurante "
            "no lo prepara." + timeout_text
        )
    elif (
        not pickup
        and distance_km is not None
        and warn_km > 0
        and float(distance_km) > warn_km
    ):
        distance_warning = (
            f"Tu pedido está a {float(distance_km):.1f} km del restaurante. "
            "Podría no ser aceptado por ningún repartidor por la distancia."
        )

    return {
        "subtotal": f"{subtotal:.2f}",
        "delivery_fee": f"{delivery_fee:.2f}",
        "platform_commission": f"{platform_commission:.2f}",
        "flat_usage_fee": f"{flat_usage_fee:.2f}",
        "discount": f"{discount:.2f}",
        "tip_amount": f"{Decimal('0') if pickup else Decimal(body.tip_amount or 0):.2f}",
        "points_redeemed": points_redeemed,
        "loyalty_discount": f"{loyalty_discount:.2f}",
        "total": f"{total:.2f}",
        "distance_km": distance_km,
        "distance_warning": distance_warning,
        "requires_courier_approval": requires_approval,
        "approval_km": approval_km,
        "approval_timeout_min": approval_timeout_min,
        "delivery_mode": "pickup" if pickup else restaurant.delivery_mode,
        "fulfillment_type": body.fulfillment_type,
    }


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == body.restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if restaurant.status != "active" and not current_user.is_superuser:
        raise HTTPException(status_code=409, detail="El restaurante todavía no está activo")

    if not current_user.is_superuser:
        open_state = await restaurant_open_state(db, restaurant)
        if not open_state["is_open_now"]:
            raise HTTPException(
                status_code=409,
                detail=f"El restaurante está cerrado. {open_state['message']}",
            )

    pickup = _is_pickup(body)
    if pickup and not restaurant.pickup_enabled:
        raise HTTPException(status_code=400, detail="Este restaurante no permite recoger pedidos")
    if not pickup and (not body.delivery_address or body.delivery_location is None):
        raise HTTPException(status_code=400, detail="Falta la dirección o ubicación de entrega")
    tip_amount = Decimal("0") if pickup else (body.tip_amount or Decimal("0"))
    if pickup:
        pickup_lat, pickup_lng = await _restaurant_coords(db, restaurant)
        delivery_address = f"{restaurant.name} — {restaurant.address}"
        delivery_location = f"SRID=4326;POINT({pickup_lng} {pickup_lat})"
        total_lat, total_lng = pickup_lat, pickup_lng
    else:
        delivery_address = body.delivery_address
        delivery_location = (
            f"SRID=4326;POINT({body.delivery_location.lng} {body.delivery_location.lat})"
        )
        total_lat, total_lng = body.delivery_location.lat, body.delivery_location.lng

    payment_method = body.payment_method
    if payment_method == "mp":
        mp_enabled = (await get_setting_value(db, "MP_ENABLED", "false")).lower() == "true"
        if not mp_enabled:
            raise HTTPException(
                status_code=400,
                detail="Mercado Pago está deshabilitado por el momento. Paga en efectivo al recibir.",
            )
    elif payment_method == "transfer":
        transfer_enabled = (await get_setting_value(db, "TRANSFER_ENABLED", "false")).lower() == "true"
        if not transfer_enabled:
            raise HTTPException(
                status_code=400,
                detail="La transferencia está deshabilitada por el momento. Paga en efectivo al recibir.",
            )
    elif payment_method != "cash":
        raise HTTPException(status_code=400, detail="Método de pago no válido")

    scheduled_for = body.scheduled_for
    if scheduled_for is not None:
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if scheduled_for < now + timedelta(minutes=10):
            raise HTTPException(
                status_code=400,
                detail="El pedido programado debe ser al menos 10 minutos después de ahora",
            )
        if scheduled_for > now + timedelta(days=14):
            raise HTTPException(
                status_code=400,
                detail="Solo se pueden programar pedidos con 14 días de anticipación",
            )

    items_data = []
    for item in body.items:
        menu_result = await db.execute(select(MenuItem).where(MenuItem.id == item.menu_item_id))
        menu_item = menu_result.scalar_one_or_none()
        if not menu_item or menu_item.restaurant_id != restaurant.id:
            raise HTTPException(status_code=400, detail=f"Item {item.menu_item_id} no válido")
        try:
            unit_price, selected = await resolve_item_options(db, menu_item, item.option_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items_data.append({
            "menu_item": menu_item, "item": item,
            "unit_price": unit_price, "options": selected,
        })

    subtotal, delivery_fee, discount, total, coupon, platform_commission, flat_usage_fee, delivery_earnings, distance_km = await calculate_order_totals(
        db, restaurant, items_data, body.coupon_code,
        delivery_lat=total_lat, delivery_lng=total_lng,
        tip_amount=tip_amount,
        pickup=pickup,
    )

    await _check_max_distance(db, distance_km, pickup)
    requires_approval, _approval_km = await _requires_courier_approval(
        db, restaurant, pickup, distance_km
    )
    approval_timeout_min = await get_approval_timeout_min(db)
    courier_deadline = None
    if requires_approval and approval_timeout_min > 0:
        courier_deadline = datetime.now(timezone.utc) + timedelta(
            minutes=approval_timeout_min
        )
    refund_holder = (body.refund_account_holder or "").strip()
    refund_bank = (body.refund_bank or "").strip()
    refund_clabe = _clean_clabe(body.refund_clabe)
    if requires_approval and payment_method == "transfer":
        if not refund_holder or not refund_bank or len(refund_clabe) != 18:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Este pedido está lejos y se paga por transferencia. "
                    "Escribe el titular, el banco y la CLABE de 18 dígitos donde "
                    "se te devolvería el dinero si ningún repartidor acepta."
                ),
            )

    points_redeemed, loyalty_discount = await apply_redemption(
        db, current_user, body.points_to_redeem,
        max(subtotal - discount, Decimal("0")),
    )
    if loyalty_discount:
        total = max(total - loyalty_discount, Decimal("0"))

    if coupon and body.coupon_code:
        coupon.current_uses += 1

    estimated_min = await calculate_estimated_time(
        db, restaurant, items_data, total_lng, total_lat, pickup=pickup,
    )
    order = Order(
        user_id=current_user.id,
        restaurant_id=restaurant.id,
        status="pending",
        delivery_mode="pickup" if pickup else restaurant.delivery_mode,
        fulfillment_type=body.fulfillment_type,
        restaurant_owes_platform=(
            max(platform_commission + flat_usage_fee - loyalty_discount, Decimal("0"))
            if payment_method == "cash" and (restaurant.delivery_mode == "own" or pickup)
            else Decimal("0")
        ),
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=total,
        delivery_address=delivery_address,
        delivery_location=delivery_location,
        notes=body.notes,
        coupon_id=coupon.id if coupon else None,
        coupon_code=body.coupon_code.upper() if body.coupon_code else None,
        discount_amount=discount,
        estimated_delivery_min=estimated_min,
        payment_method=payment_method,
        platform_commission=platform_commission,
        flat_usage_fee=flat_usage_fee,
        delivery_earnings=delivery_earnings,
        delivery_distance_km=distance_km,
        tip_amount=tip_amount,
        scheduled_for=scheduled_for,
        points_redeemed=points_redeemed,
        loyalty_discount=loyalty_discount,
        requires_courier_approval=requires_approval,
        courier_approval_deadline=courier_deadline,
        refund_account_holder=refund_holder or None,
        refund_bank=refund_bank or None,
        refund_clabe=refund_clabe or None,
    )
    db.add(order)
    await db.flush()

    for entry in items_data:
        menu_item = entry["menu_item"]
        item = entry["item"]
        unit_price = entry["unit_price"]
        line_subtotal = unit_price * item.quantity
        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=menu_item.id,
            name=menu_item.name,
            quantity=item.quantity,
            unit_price=unit_price,
            subtotal=line_subtotal,
            notes=item.notes,
        )
        db.add(order_item)
        await db.flush()
        for selected in entry["options"]:
            db.add(OrderItemOption(
                order_item_id=order_item.id,
                option_id=selected["option_id"],
                group_name=selected["group_name"],
                name=selected["name"],
                price_delta=selected["price_delta"],
                portion=selected.get("portion", 1),
            ))

    await db.commit()
    await db.refresh(order)
    result = await db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    )
    schedule_new_order(str(order.id))
    if requires_approval:
        # El repartidor se busca desde que se paga, no cuando el restaurante confirma.
        schedule_available_order(str(order.id), False)
    return result.scalar_one()


@router.patch("/{order_id}/refund-account", response_model=OrderOut)
async def update_refund_account(
    order_id: str,
    body: RefundAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="No puedes editar este pedido")
    if order.payment_method != "transfer":
        raise HTTPException(
            status_code=400,
            detail="Solo los pedidos pagados por transferencia necesitan cuenta de reembolso",
        )
    clabe = _clean_clabe(body.refund_clabe)
    if len(clabe) != 18:
        raise HTTPException(status_code=400, detail="La CLABE debe tener 18 dígitos")
    order.refund_account_holder = body.refund_account_holder.strip()
    order.refund_bank = body.refund_bank.strip()
    order.refund_clabe = clabe
    await db.commit()
    await db.refresh(order)
    return order


@router.get("", response_model=list[OrderOut])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Order)
        .where(Order.user_id == current_user.id)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/cancellation-policy", response_model=CancellationPolicyOut)
async def cancellation_policy(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_policy(db)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if not current_user.is_superuser and order.user_id != current_user.id:
        allowed = False
        resto_result = await db.execute(
            select(Restaurant).where(Restaurant.id == order.restaurant_id)
        )
        restaurant = resto_result.scalar_one_or_none()
        if restaurant and await have_role(db, restaurant.id, current_user, ORDER_ROLES):
            allowed = True
        if not allowed:
            dp_result = await db.execute(
                select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
            )
            dp = dp_result.scalar_one_or_none()
            allowed = bool(dp and order.delivery_person_id == dp.id)
        if not allowed:
            raise HTTPException(status_code=403, detail="No tienes acceso a este pedido")
    return order_out(
        order,
        can_see_refund=bool(current_user.is_superuser or order.user_id == current_user.id),
    )


@router.get("/{order_id}/tracking", response_model=TrackingOut)
async def get_order_tracking(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    allowed = order.user_id == current_user.id or current_user.is_superuser
    if not allowed:
        resto_result = await db.execute(
            select(Restaurant).where(Restaurant.id == order.restaurant_id)
        )
        restaurant = resto_result.scalar_one_or_none()
        allowed = bool(restaurant and await have_role(db, restaurant.id, current_user, ORDER_ROLES))
    if not allowed:
        dp_result = await db.execute(
            select(DeliveryPerson).where(DeliveryPerson.user_id == current_user.id)
        )
        dp = dp_result.scalar_one_or_none()
        allowed = bool(dp and order.delivery_person_id == dp.id)
    if not allowed:
        raise HTTPException(status_code=403, detail="No tienes acceso a este pedido")

    return await build_tracking(db, order)


@router.patch("/{order_id}/status", response_model=OrderOut)
async def update_order_status(
    order_id: str,
    body: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    resto_result = await db.execute(
        select(Restaurant).where(Restaurant.id == order.restaurant_id)
    )
    restaurant = resto_result.scalar_one_or_none()
    if not current_user.is_superuser and not (restaurant and await have_role(db, restaurant.id, current_user, ORDER_ROLES)):
        raise HTTPException(status_code=403, detail="No puedes cambiar el estado de este pedido")

    if (
        order.status == "awaiting_courier"
        and body.status == "preparing"
        and not order.delivery_person_id
    ):
        raise HTTPException(
            status_code=400,
            detail="Espera a que un repartidor acepte el pedido antes de prepararlo",
        )

    requested = body.status
    if (
        requested == "confirmed"
        and order.requires_courier_approval
        and order.delivery_mode == "platform"
    ):
        requested = "preparing" if order.delivery_person_id else "awaiting_courier"

    order.status = requested
    now = datetime.now(timezone.utc)
    if requested == "awaiting_courier":
        order.awaiting_courier_at = now
        if order.courier_approval_deadline is None:
            timeout_min = await get_approval_timeout_min(db)
            order.courier_approval_deadline = (
                now + timedelta(minutes=timeout_min) if timeout_min > 0 else None
            )
        if order.confirmed_at is None:
            order.confirmed_at = now
    elif requested == "confirmed" and order.confirmed_at is None:
        order.confirmed_at = now
    elif (
        requested == "preparing"
        and order.requires_courier_approval
        and order.confirmed_at is None
    ):
        order.confirmed_at = now
    elif requested == "picked_up" and order.picked_up_at is None:
        order.picked_up_at = now
    elif requested == "delivered" and order.delivered_at is None:
        order.delivered_at = now

    # En los pedidos lejanos el repartidor ya está asignado: al quedar listo
    # pasa directo a reparto para que pueda recogerlo.
    if (
        requested == "ready"
        and order.requires_courier_approval
        and order.delivery_person_id
    ):
        order.status = "in_delivery"
    final_status = order.status

    if final_status == "delivered":
        await award_on_delivery(db, order)
    await db.commit()
    await db.refresh(order)
    ws_manager = _get_ws_manager()
    await ws_manager.notify_order_status(str(order.id), final_status)
    schedule_order_status(str(order.id), final_status)
    if final_status == "awaiting_courier":
        schedule_available_order(str(order.id), False)
    elif (
        final_status in ("confirmed", "ready")
        and order.delivery_mode == "platform"
        and not order.delivery_person_id
    ):
        schedule_available_order(str(order.id), final_status == "ready")
    elif final_status == "in_delivery" and order.requires_courier_approval:
        schedule_courier_ready(str(order.id))
    return order


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    order_id: str,
    body: CancelOrderRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    resto_result = await db.execute(
        select(Restaurant).where(Restaurant.id == order.restaurant_id)
    )
    restaurant = resto_result.scalar_one_or_none()

    if current_user.is_superuser:
        role = "admin"
    elif restaurant and await have_role(db, restaurant.id, current_user, ORDER_ROLES):
        role = "restaurant"
    elif order.user_id == current_user.id:
        role = "customer"
    else:
        raise HTTPException(status_code=403, detail="No puedes cancelar este pedido")

    try:
        await apply_cancellation(
            db,
            order,
            actor_id=current_user.id,
            role=role,
            reason=body.reason if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(order)
    result = await db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    )
    order = result.scalar_one()
    ws_manager = _get_ws_manager()
    await ws_manager.notify_order_status(str(order.id), "cancelled")
    schedule_order_status(str(order.id), "cancelled")
    return order
