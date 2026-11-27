from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re
import uuid

import clabe
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.constants import OrderStatus
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.appointment import Appointment
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_item_option import OrderItemOption
from app.models.recarga_order import RecargaOrder
from app.models.receipt_validation import ReceiptValidation
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.rounding import round_half_down
from app.schemas.order import (
    CancelOrderRequest,
    CancellationPolicyOut,
    OrderCreate,
    OrderOut,
    OrderStatusUpdate,
    RefundAccountUpdate,
    TrackingOut,
    TransferValidationRequest,
)
from app.services.audit_service import log_action
from app.services.cancellation_service import apply_cancellation, can_cancel, get_policy
from app.services.cep_validation_service import CepValidationError, validate_transfer
from app.services.coverage_service import ensure_coverage
from app.services.file_service import save_document
from app.services.receipt_validation_service import (
    TRANSFER as TRANSFER_RECEIPT,
    create_and_validate,
)
from app.services.restaurant_access import ORDER_ROLES, have_role
from app.services.estimation_service import calculate_estimated_time
from app.services.order_service import (
    calculate_order_totals,
    delivery_ops_v2_enabled,
    get_approval_timeout_min,
    get_int_setting,
    get_setting_value,
    resolve_item_options,
)
from app.services.order_serialization import order_out
from app.services.order_transfer_service import apply_preapproved_transfer
from app.services import courier_availability, delivery_ops_service, recarga_service, sivetel_service
from app.services.loyalty_service import apply_redemption, preview_redemption, award_on_delivery
from app.services.push_service import schedule_available_order, schedule_courier_preparing, schedule_courier_ready, schedule_customer_early_prep, schedule_new_order, schedule_near_closing_order, schedule_no_courier_wait, schedule_order_release, schedule_order_status, schedule_scheduled_outside_hours, schedule_admin_transfer_review
from app.services.schedule_service import minutes_to_close, restaurant_open_state, schedule_state_at
from app.services.scheduled_service import ScheduledOrderError, enforce_scheduled_rules
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


async def _validate_checkout_recharge(
    db: AsyncSession, body: OrderCreate
) -> None:
    """Valida la recarga solo al crear el pedido, no en la vista previa."""
    amount = Decimal(body.recharge_amount or 0)
    code = (body.recharge_product_code or "").strip().upper()
    if amount <= 0 and not code:
        body.recharge_company = None
        body.recharge_phone = None
        body.recharge_product_code = None
        body.recharge_product_description = None
        body.recharge_kind = None
        body.recharge_amount = Decimal("0")
        return
    if _is_pickup(body):
        raise HTTPException(
            status_code=400,
            detail="La recarga solo aplica con entrega a domicilio.",
        )
    digits = "".join(ch for ch in str(body.recharge_phone or "") if ch.isdigit())
    if len(digits) != 10:
        raise HTTPException(
            status_code=400,
            detail="Escribe un número de 10 dígitos para la recarga.",
        )

    if code:
        if not await recarga_service.recharges_enabled(db):
            raise HTTPException(
                status_code=400,
                detail="Las recargas de tiempo aire no están disponibles por ahora.",
            )
        config = await sivetel_service.load_config(db)
        if config is None:
            raise HTTPException(
                status_code=400,
                detail="Sivetel no está configurado.",
            )
        try:
            client = sivetel_service.SivetelClient(config)
            products = await sivetel_service.obtener_catalogo(client)
        except sivetel_service.SivetelError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"No se pudo consultar el catálogo: {exc.message}",
            ) from exc
        provider = await sivetel_service.provider_status(client)
        if not provider["available"]:
            raise HTTPException(status_code=503, detail=provider["message"])
        product = sivetel_service.find_product(products, code)
        if product is None:
            raise HTTPException(
                status_code=400,
                detail="El producto de recarga ya no está disponible.",
            )
        body.recharge_product_code = product["code"]
        body.recharge_company = product["company"]
        body.recharge_product_description = product["description"]
        body.recharge_kind = product["kind"]
        body.recharge_amount = Decimal(product["amount"])
        body.recharge_phone = digits
        return

    config = await sivetel_service.load_config(db)
    if config is None:
        raise HTTPException(
            status_code=400,
            detail="Sivetel no está configurado.",
        )
    try:
        client = sivetel_service.SivetelClient(config)
        provider = await sivetel_service.provider_status(client)
    except sivetel_service.SivetelError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo consultar Sivetel: {exc.message}",
        ) from exc
    if not provider["available"]:
        raise HTTPException(status_code=503, detail=provider["message"])

    if amount < recarga_service.MIN_RECHARGE:
        raise HTTPException(
            status_code=400,
            detail="La recarga mínima es de $10.",
        )
    if amount > recarga_service.MAX_RECHARGE:
        raise HTTPException(
            status_code=400,
            detail="La recarga supera el máximo permitido.",
        )
    company = (body.recharge_company or "").strip()
    if len(company) < 2:
        raise HTTPException(
            status_code=400,
            detail="Escribe la compañía de la recarga.",
        )
    body.recharge_company = company
    body.recharge_phone = digits


DEFAULT_EMAIL_GRACE_ORDERS = 3


async def _email_verification_block(
    db: AsyncSession, user: User
) -> str | None:
    """Mensaje de bloqueo si debe confirmar el correo; None si puede pedir.

    Da un margen de pedidos (3 por defecto) para que la persona pruebe el
    servicio. Al agotarlo, debe confirmar el correo. Si el administrador
    activa "Exigir correo confirmado", se pide desde el primer pedido.
    """
    if user.email_verified or user.is_superuser:
        return None

    required = (
        await get_setting_value(db, "REQUIRE_EMAIL_VERIFICATION", "false")
    ).strip().lower() == "true"
    if required:
        return (
            "Confirma tu correo antes de hacer tu pedido. "
            "Revisa tu bandeja o usa «Reenviar correo» en el aviso superior."
        )

    try:
        grace = int(
            (await get_setting_value(
                db, "EMAIL_VERIFICATION_GRACE_ORDERS", str(DEFAULT_EMAIL_GRACE_ORDERS)
            )).strip()
        )
    except (TypeError, ValueError):
        grace = DEFAULT_EMAIL_GRACE_ORDERS
    grace = max(0, grace)
    if grace <= 0:
        return (
            "Confirma tu correo antes de hacer tu pedido. "
            "Revisa tu bandeja o usa «Reenviar correo» en el aviso superior."
        )

    used = int(
        await db.scalar(
            select(func.count(Order.id)).where(
                Order.user_id == user.id,
                Order.status != OrderStatus.CANCELLED.value,
            )
        ) or 0
    )
    if used < grace:
        return None

    return (
        f"Llegaste al límite de {grace} pedidos sin confirmar tu correo. "
        "Confírmalo para seguir pidiendo: revisa tu bandeja o usa "
        "«Reenviar correo» en el aviso superior."
    )


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
    if not pickup and not getattr(restaurant, "delivery_enabled", True):
        raise HTTPException(
            status_code=400,
            detail="Este negocio no tiene reparto a domicilio. Elige recoger en el negocio.",
        )
    if not pickup and body.delivery_location is None:
        raise HTTPException(status_code=400, detail="Falta la ubicación de entrega")
    items_data = []
    for item in body.items:
        menu_result = await db.execute(select(MenuItem).where(MenuItem.id == item.menu_item_id))
        menu_item = menu_result.scalar_one_or_none()
        if not menu_item:
            raise HTTPException(
                status_code=400,
                detail="Uno de los productos ya no está disponible",
            )
        if menu_item.restaurant_id != restaurant.id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Todos los productos deben ser del mismo restaurante. "
                    "Un pedido solo puede incluir productos de un negocio."
                ),
            )
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
    if not pickup:
        await ensure_coverage(db, lat, lng)
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
    if not pickup and not getattr(restaurant, "delivery_enabled", True):
        raise HTTPException(
            status_code=400,
            detail="Este negocio no tiene reparto a domicilio. Elige recoger en el negocio.",
        )
    if not pickup and body.delivery_location is None:
        raise HTTPException(status_code=400, detail="Falta la ubicación de entrega")
    items_data = []
    for item in body.items:
        menu_result = await db.execute(select(MenuItem).where(MenuItem.id == item.menu_item_id))
        menu_item = menu_result.scalar_one_or_none()
        if not menu_item:
            raise HTTPException(
                status_code=400,
                detail="Uno de los productos ya no está disponible",
            )
        if menu_item.restaurant_id != restaurant.id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Todos los productos deben ser del mismo restaurante. "
                    "Un pedido solo puede incluir productos de un negocio."
                ),
            )
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
    if not pickup:
        await ensure_coverage(db, lat, lng)
    subtotal, delivery_fee, discount, total, coupon, platform_commission, flat_usage_fee, delivery_earnings, distance_km, coupon_error = await calculate_order_totals(
        db, restaurant, items_data, body.coupon_code,
        delivery_lat=lat, delivery_lng=lng,
        tip_amount=Decimal("0") if pickup else round_half_down(body.tip_amount),
        pickup=pickup,
    )
    if coupon_error:
        raise HTTPException(status_code=400, detail=coupon_error)
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

    recharge_amount = round_half_down(
        min(
            max(Decimal(body.recharge_amount or 0), Decimal("0")),
            recarga_service.MAX_RECHARGE,
        )
    ) if await recarga_service.recharges_enabled(db) else Decimal("0.00")
    recharge_fee = recarga_service.checkout_fee(body.payment_method, recharge_amount)
    recharge_total = round_half_down(recharge_amount + recharge_fee)
    total_to_pay = round_half_down(total + recharge_total)

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

    ops_v2 = await delivery_ops_v2_enabled(db)
    available_couriers = 0
    no_courier = False
    no_courier_wait_min = await get_int_setting(db, "NO_COURIER_WAIT_MIN", 30)
    no_courier_decision_min = await get_int_setting(
        db, "NO_COURIER_DECISION_MIN", 15
    )
    near_closing = False
    minutes_close = None
    near_closing_min = await get_int_setting(db, "NEAR_CLOSING_MIN", 30)
    if ops_v2 and not pickup and restaurant.delivery_mode == "platform":
        available_couriers = await courier_availability.available_courier_count(db)
        no_courier = available_couriers == 0
        minutes_close = await minutes_to_close(db, restaurant)
        near_closing = (
            minutes_close is not None and minutes_close <= near_closing_min
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
        "recharge_company": body.recharge_company,
        "recharge_phone": body.recharge_phone,
        "recharge_product_code": body.recharge_product_code,
        "recharge_product_description": body.recharge_product_description,
        "recharge_kind": body.recharge_kind,
        "recharge_amount": f"{recharge_amount:.2f}",
        "recharge_fee": f"{recharge_fee:.2f}",
        "recharge_total": f"{recharge_total:.2f}",
        "total_to_pay": f"{total_to_pay:.2f}",
        "distance_km": distance_km,
        "distance_warning": distance_warning,
        "requires_courier_approval": requires_approval,
        "approval_km": approval_km,
        "approval_timeout_min": approval_timeout_min,
        "available_couriers": available_couriers,
        "no_courier": no_courier,
        "no_courier_wait_min": no_courier_wait_min,
        "no_courier_decision_min": no_courier_decision_min,
        "near_closing": near_closing,
        "minutes_to_close": minutes_close,
        "near_closing_min": near_closing_min,
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

    await _validate_checkout_recharge(db, body)
    if (body.recharge_amount or 0) > 0 and not await recarga_service.recharges_enabled(db):
        raise HTTPException(
            status_code=400,
            detail="Las recargas de tiempo aire no están disponibles por ahora.",
        )

    if not current_user.is_superuser:
        email_block = await _email_verification_block(db, current_user)
        if email_block:
            raise HTTPException(status_code=403, detail=email_block)

    appointment_link = None
    if body.appointment_id:
        try:
            appointment_uuid = uuid.UUID(str(body.appointment_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="Cita inválida") from exc
        appointment = await db.get(Appointment, appointment_uuid)
        if (
            not appointment
            or appointment.restaurant_id != restaurant.id
            or appointment.client_user_id != current_user.id
        ):
            raise HTTPException(status_code=400, detail="La cita no pertenece a este negocio")
        if appointment.status not in ("pending", "confirmed"):
            raise HTTPException(status_code=400, detail="La cita ya está cerrada")
        appointment_link = appointment.id

    if (
        not current_user.is_superuser
        and not appointment_link
        and body.scheduled_for is None
    ):
        open_state = await restaurant_open_state(db, restaurant)
        if not restaurant.is_open:
            raise HTTPException(
                status_code=409,
                detail="El negocio no está recibiendo pedidos en este momento.",
            )
        if open_state["has_schedule"] and not open_state["is_open_now"]:
            raise HTTPException(
                status_code=409,
                detail=f"El negocio está cerrado. {open_state['message']}",
            )

    pickup = _is_pickup(body)
    if pickup and not restaurant.pickup_enabled:
        raise HTTPException(status_code=400, detail="Este restaurante no permite recoger pedidos")
    if not pickup and not getattr(restaurant, "delivery_enabled", True):
        raise HTTPException(
            status_code=400,
            detail="Este negocio no tiene reparto a domicilio. Elige recoger en el negocio.",
        )
    if not pickup and (not body.delivery_address or body.delivery_location is None):
        raise HTTPException(status_code=400, detail="Falta la dirección o ubicación de entrega")
    if appointment_link and not pickup:
        raise HTTPException(
            status_code=400,
            detail="Los productos de una cita se recogen en el negocio",
        )
    tip_amount = Decimal("0") if pickup else round_half_down(body.tip_amount or Decimal("0"))
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

    if not pickup:
        await ensure_coverage(db, total_lat, total_lng)

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
        open_transfer = await db.scalar(
            select(Order.id)
            .where(
                Order.user_id == current_user.id,
                Order.payment_method == "transfer",
                Order.payment_status != "approved",
                Order.status != "cancelled",
            )
            .limit(1)
        )
        if open_transfer:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Ya tienes un pedido por transferencia pendiente. "
                    "Termina ese pago, cámbialo a efectivo o cancélalo antes "
                    "de crear otro."
                ),
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
        if not menu_item:
            raise HTTPException(
                status_code=400,
                detail="Uno de los productos ya no está disponible",
            )
        if menu_item.restaurant_id != restaurant.id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Todos los productos deben ser del mismo restaurante. "
                    "Un pedido solo puede incluir productos de un negocio."
                ),
            )
        try:
            unit_price, selected = await resolve_item_options(db, menu_item, item.option_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items_data.append({
            "menu_item": menu_item, "item": item,
            "unit_price": unit_price, "options": selected,
        })

    subtotal, delivery_fee, discount, total, coupon, platform_commission, flat_usage_fee, delivery_earnings, distance_km, coupon_error = await calculate_order_totals(
        db, restaurant, items_data, body.coupon_code,
        delivery_lat=total_lat, delivery_lng=total_lng,
        tip_amount=tip_amount,
        pickup=pickup,
    )
    if coupon_error:
        raise HTTPException(status_code=400, detail=coupon_error)

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

    ops_v2 = await delivery_ops_v2_enabled(db)
    no_courier_hold = False
    near_closing = False
    business_deadline = None
    scheduled_outside_hours = False
    scheduled_approval_status = None
    scheduled_approval_deadline = None
    if scheduled_for is not None and not pickup:
        schedule_state = await schedule_state_at(db, restaurant, scheduled_for)
        if schedule_state["has_schedule"] and not schedule_state["is_open"]:
            scheduled_outside_hours = True
            scheduled_approval_status = "pending"
            approval_min = await get_int_setting(
                db, "SCHEDULED_APPROVAL_MIN", 30
            )
            scheduled_approval_deadline = datetime.now(timezone.utc) + timedelta(
                minutes=max(approval_min, 1)
            )
    if (
        ops_v2
        and not pickup
        and restaurant.delivery_mode == "platform"
        and scheduled_for is None
    ):
        available = await courier_availability.available_courier_count(db)
        if available == 0:
            if body.no_courier_action != "wait":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "No hay repartidores disponibles ahora. "
                        "Elige recoger en el negocio."
                    ),
                )
            requires_approval = True
            no_courier_hold = True
            wait_min = await get_int_setting(db, "NO_COURIER_WAIT_MIN", 30)
            courier_deadline = datetime.now(timezone.utc) + timedelta(
                minutes=wait_min
            )
        minutes_close = await minutes_to_close(db, restaurant)
        near_closing_min = await get_int_setting(db, "NEAR_CLOSING_MIN", 30)
        if (
            minutes_close is not None
            and minutes_close <= near_closing_min
        ):
            near_closing = True
            response_min = await get_int_setting(
                db, "NEAR_CLOSING_RESPONSE_MIN", 10
            )
            business_deadline = datetime.now(timezone.utc) + timedelta(
                minutes=max(response_min, 1)
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

    recharge_amount = round_half_down(Decimal(body.recharge_amount or 0))
    recharge_fee = recarga_service.checkout_fee(payment_method, recharge_amount)
    recharge_total = round_half_down(recharge_amount + recharge_fee)
    if recharge_amount > 0 and restaurant.delivery_mode != "platform":
        raise HTTPException(
            status_code=400,
            detail="La recarga de tiempo aire solo está disponible con reparto de TuPedidoJR.",
        )

    debt_charged = Decimal("0")
    pending_balance = Decimal(str(current_user.pending_balance or 0))
    if pending_balance > 0:
        mode = body.debt_payment_mode or "full"
        if payment_method == "cash" and mode == "installments":
            try:
                max_count = int(await get_setting_value(db, "INSTALLMENT_MAX_COUNT", "5"))
            except (TypeError, ValueError):
                max_count = 5
            max_count = max(max_count, 2)
            if (current_user.pending_installments or 0) <= 0:
                current_user.pending_installments = max_count
                current_user.installment_amount = round_half_down(pending_balance / max_count)
            amount = current_user.installment_amount or round_half_down(pending_balance / max_count)
            amount = min(amount, pending_balance)
            current_user.pending_installments = max((current_user.pending_installments or 1) - 1, 0)
        else:
            amount = pending_balance
            current_user.pending_installments = 0
            current_user.installment_amount = Decimal("0")
        if amount > 0:
            debt_charged = round_half_down(amount)
            total = round_half_down(total + debt_charged)
            current_user.pending_balance = round_half_down(pending_balance - debt_charged)

    if coupon and body.coupon_code:
        coupon.current_uses += 1

    estimated_min = await calculate_estimated_time(
        db, restaurant, items_data, total_lng, total_lat, pickup=pickup,
    )
    order = Order(
        user_id=current_user.id,
        restaurant_id=restaurant.id,
        appointment_id=appointment_link,
        status="awaiting_courier" if no_courier_hold else "pending",
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
        debt_charged=debt_charged,
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
        scheduled_outside_hours=scheduled_outside_hours,
        scheduled_approval_status=scheduled_approval_status,
        scheduled_approval_deadline=scheduled_approval_deadline,
        points_redeemed=points_redeemed,
        loyalty_discount=loyalty_discount,
        requires_courier_approval=requires_approval,
        no_courier_hold=no_courier_hold,
        courier_alert_at=None,
        near_closing=near_closing,
        business_confirmation_deadline=business_deadline,
        admin_delivery=False,
        courier_approval_deadline=courier_deadline,
        refund_account_holder=refund_holder or None,
        refund_bank=refund_bank or None,
        refund_clabe=refund_clabe or None,
        recharge_company=body.recharge_company if recharge_amount > 0 else None,
        recharge_phone=body.recharge_phone if recharge_amount > 0 else None,
        recharge_product_code=body.recharge_product_code if recharge_amount > 0 else None,
        recharge_product_description=body.recharge_product_description if recharge_amount > 0 else None,
        recharge_kind=body.recharge_kind if recharge_amount > 0 else None,
        recharge_amount=recharge_amount,
        recharge_fee=recharge_fee,
        recharge_status="pending" if recharge_amount > 0 else None,
    )
    db.add(order)
    await db.flush()

    if recharge_amount > 0:
        db.add(RecargaOrder(
            user_id=current_user.id,
            customer_name=current_user.name,
            order_id=order.id,
            origin="checkout",
            company=body.recharge_company,
            phone=body.recharge_phone,
            product_code=body.recharge_product_code,
            product_description=body.recharge_product_description,
            product_kind=body.recharge_kind,
            amount=recharge_amount,
            fee=recharge_fee,
            total=recharge_total,
            payment_method=payment_method,
            payment_status="paid" if payment_method == "cash" else "pending",
            status="pending",
            debt_applied=True,
            credit_applied=True,
            paid_at=datetime.now(timezone.utc) if payment_method == "cash" else None,
        ))

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
    if payment_method != "transfer" or order.payment_status == "approved":
        schedule_new_order(str(order.id))
        if requires_approval:
            # El repartidor se busca desde que se paga, no cuando el restaurante confirma.
            schedule_available_order(str(order.id), False)
        if near_closing:
            schedule_near_closing_order(str(order.id))
        if no_courier_hold:
            schedule_no_courier_wait(str(order.id))
        if scheduled_outside_hours:
            schedule_scheduled_outside_hours(str(order.id))
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
    if (
        not current_user.is_superuser
        and order.user_id != current_user.id
        and order.payment_method == "transfer"
        and order.payment_status != "approved"
    ):
        raise HTTPException(
            status_code=403,
            detail="El pago aún no está confirmado para este pedido",
        )
    customer = await db.get(User, order.user_id)
    return order_out(
        order,
        can_see_refund=bool(current_user.is_superuser or order.user_id == current_user.id),
        customer_phone=customer.phone if customer else None,
    )


@router.post("/{order_id}/switch-to-pickup", response_model=OrderOut)
async def customer_switch_to_pickup(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """El cliente cambia a recoger cuando se agotó la espera de repartidor."""
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="No puedes modificar este pedido")
    if not order.no_courier_hold and order.status != "awaiting_courier":
        raise HTTPException(
            status_code=400,
            detail="Este pedido no está esperando repartidor",
        )
    try:
        refund = await delivery_ops_service.switch_order_to_pickup(
            db, order, actor_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await log_action(
        db,
        current_user.id,
        "order.customer_switch_to_pickup",
        "order",
        order.id,
        {"refund_amount": str(refund)},
    )
    await db.commit()
    await db.refresh(order)
    schedule_new_order(str(order.id))
    schedule_order_status(str(order.id), order.status)
    customer = await db.get(User, order.user_id)
    return order_out(
        order,
        can_see_refund=True,
        customer_phone=customer.phone if customer else None,
    )


async def _apply_cep_payment(
    db: AsyncSession,
    order: Order,
    current_user: User,
    *,
    tracking_key: str,
    sender_bank: str | None,
    receiver_bank: str,
    cep_payload: dict,
) -> None:
    """Marca el pedido como pagado tras una validación CEP exitosa."""
    key = (tracking_key or "").strip()
    existing = await db.scalar(
        select(Order.id).where(
            Order.transfer_tracking_key == key,
            Order.id != order.id,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Esa transferencia ya fue usada en otro pedido.",
        )

    order.transfer_tracking_key = key
    order.cep_status = "valid"
    order.cep_validated_at = datetime.now(timezone.utc)
    order.cep_sender_bank = sender_bank
    order.cep_receiver_bank = receiver_bank
    order.cep_payload = cep_payload
    order.payment_status = "approved"
    await recarga_service.confirm_checkout_recharge(db, order)

    from app.services.payout_service import credit_courier_for_order

    await credit_courier_for_order(db, order)
    await log_action(
        db,
        current_user.id,
        "transfer.cep_validated",
        "order",
        order.id,
        {"clave_rastreo": key, "total": str(order.total_to_pay)},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Esa transferencia ya fue usada en otro pedido.",
        )
    schedule_order_release(str(order.id))


async def _load_order_for_transfer(
    db: AsyncSession, order_id: str, current_user: User
) -> Order:
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order or (not current_user.is_superuser and order.user_id != current_user.id):
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.payment_method != "transfer":
        raise HTTPException(
            status_code=400, detail="Este pedido no es por transferencia"
        )
    if order.status == "cancelled":
        raise HTTPException(status_code=400, detail="El pedido está cancelado")
    return order


def _normalize_bank_name(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _cep_code_for_bank_name(value) -> str | None:
    target = _normalize_bank_name(value)
    if not target:
        return None
    for code, name in clabe.BANK_NAMES.items():
        if _normalize_bank_name(name) == target:
            return code
    return None


def _match_receiver_account(extracted: dict, accounts: list[dict]) -> dict | None:
    text = " ".join(
        str(extracted.get(key) or "")
        for key in ("recipient", "account", "beneficiaryName", "reference")
    )
    digits = "".join(ch for ch in text if ch.isdigit())
    for account in accounts:
        if account["clabe"] and account["clabe"] in digits:
            return account
    return None


async def _transfer_receiver_accounts(db: AsyncSession) -> list[dict]:
    accounts: list[dict] = []
    for suffix in ("", "_2"):
        clabe_value = "".join(
            ch
            for ch in (
                await get_setting_value(db, f"BANK_CLABE{suffix}", "")
            ).strip()
            if ch.isdigit()
        )
        if len(clabe_value) != 18:
            continue
        bank_code = clabe.BANKS.get(clabe_value[:3])
        if not bank_code:
            continue
        accounts.append({
            "clabe": clabe_value,
            "bank_code": bank_code,
            "bank_name": (
                await get_setting_value(db, f"BANK_NAME{suffix}", "")
            ).strip(),
            "holder": (
                await get_setting_value(db, f"BANK_ACCOUNT_HOLDER{suffix}", "")
            ).strip(),
        })
    if not accounts:
        raise HTTPException(
            status_code=400,
            detail="La cuenta bancaria de la plataforma no está configurada.",
        )
    return accounts


@router.post("/{order_id}/switch-to-cash")
async def switch_order_to_cash(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permite pasar un pedido por transferencia a efectivo antes de pagar."""
    order = await _load_order_for_transfer(db, order_id, current_user)
    if order.payment_status == "approved":
        raise HTTPException(
            status_code=400,
            detail="El pago ya está confirmado; no se puede cambiar a efectivo.",
        )
    if order.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="El pedido ya no se puede modificar.",
        )

    order.payment_method = "cash"
    order.payment_status = "pending"
    order.cep_status = None
    order.transfer_tracking_key = None
    order.cep_validated_at = None
    order.cep_sender_bank = None
    order.cep_receiver_bank = None
    order.cep_payload = None

    if (order.recharge_amount or 0) > 0:
        order.recharge_fee = recarga_service.CHECKOUT_RECHARGE_FEE
        recarga = await recarga_service.get_checkout_recarga(db, order.id)
        if recarga is not None:
            recarga.fee = order.recharge_fee
            recarga.total = (order.recharge_amount or 0) + order.recharge_fee
            recarga.payment_method = "cash"
            recarga.payment_status = "paid"
            recarga.paid_at = datetime.now(timezone.utc)

    record = await db.scalar(
        select(ReceiptValidation)
        .where(
            ReceiptValidation.entity_type == "order_transfer",
            ReceiptValidation.entity_id == order.id,
        )
        .order_by(ReceiptValidation.created_at.desc())
        .limit(1)
    )
    if record and record.status not in ("approved", "high"):
        record.status = "rejected"
        record.summary = "El cliente cambió el pago a efectivo."

    await db.commit()
    schedule_order_release(str(order.id))
    return {
        "payment_method": "cash",
        "message": (
            "Cambiamos tu pago a efectivo. "
            "El negocio ya puede ver tu pedido."
        ),
    }


@router.post("/{order_id}/validate-transfer")
async def validate_transfer_payment(
    order_id: str,
    body: TransferValidationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = await _load_order_for_transfer(db, order_id, current_user)
    if order.payment_status == "approved":
        return {
            "payment_status": "approved",
            "cep_status": order.cep_status or "valid",
            "message": "Este pedido ya está pagado.",
        }

    enabled = (
        await get_setting_value(db, "CEP_ENABLED", "false")
    ).lower() == "true"
    if not enabled:
        raise HTTPException(
            status_code=400,
            detail=(
                "La validación automática con Banxico no está activada. "
                "Envía tu comprobante a soporte o espera la revisión."
            ),
        )

    accounts = await _transfer_receiver_accounts(db)
    sender_bank = str(body.sender_bank or "").strip()
    receiver = next(
        (
            account
            for account in accounts
            if account["bank_code"] != sender_bank
        ),
        accounts[0],
    )
    receiver_account = receiver["clabe"]
    receiver_bank = receiver["bank_code"]

    key = body.clave_rastreo.strip()
    existing = await db.scalar(
        select(Order.id).where(
            Order.transfer_tracking_key == key,
            Order.id != order.id,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Esa transferencia ya fue usada en otro pedido.",
        )

    force_closed = (
        await get_setting_value(db, "CEP_FORCE_CLOSED", "false")
    ).lower() == "true"
    if force_closed:
        order.cep_status = "review"
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail=(
                "Banxico está cerrado (simulación). Sube tu comprobante "
                "para validarlo con el respaldo de Gemini."
            ),
        )

    amount_cents = int((Decimal(order.total_to_pay or 0) * 100).to_integral_value())
    transfer_date = body.transfer_date or date.today()
    try:
        cep = await validate_transfer(
            clave_rastreo=key,
            sender_bank=body.sender_bank,
            receiver_bank=receiver_bank,
            receiver_account=receiver_account,
            amount_cents=amount_cents,
            transfer_date=transfer_date,
        )
    except CepValidationError as exc:
        status_by_error = {
            "not_found": 404,
            "pending": 409,
            "rate_limited": 429,
            "invalid_bank": 400,
            "invalid_account": 400,
            "missing_key": 400,
            "invalid_amount": 400,
            "invalid_date": 400,
            "closed": 409,
            "amount_mismatch": 409,
            "account_mismatch": 409,
            "receiver_mismatch": 409,
            "sender_mismatch": 409,
            "key_mismatch": 409,
            "same_bank": 409,
            "error": 502,
        }
        review_statuses = {
            "not_found",
            "pending",
            "rate_limited",
            "closed",
            "amount_mismatch",
            "account_mismatch",
            "receiver_mismatch",
            "sender_mismatch",
            "key_mismatch",
            "same_bank",
            "error",
        }
        if exc.status in review_statuses:
            order.cep_status = "review"
            await db.commit()
        raise HTTPException(
            status_code=status_by_error.get(exc.status, 502),
            detail=exc.message,
        ) from exc

    await _apply_cep_payment(
        db,
        order,
        current_user,
        tracking_key=key,
        sender_bank=body.sender_bank,
        receiver_bank=receiver_bank,
        cep_payload=cep,
    )
    return {
        "payment_status": "approved",
        "cep_status": "valid",
        "message": "Pago validado por Banxico. El negocio ya puede preparar tu pedido.",
    }


@router.post("/{order_id}/validate-transfer-receipt")
async def validate_transfer_receipt(
    order_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lee el comprobante con apiCEP y lo valida contra Banxico."""
    order = await _load_order_for_transfer(db, order_id, current_user)
    if order.payment_status == "approved":
        return {
            "payment_status": "approved",
            "cep_status": order.cep_status or "valid",
            "message": "Este pedido ya está pagado.",
        }

    enabled = (
        await get_setting_value(db, "CEP_ENABLED", "false")
    ).lower() == "true"
    if not enabled:
        raise HTTPException(
            status_code=400,
            detail="La validación automática con Banxico no está activada.",
        )
    provider = (
        await get_setting_value(db, "RECEIPT_VALIDATION_PROVIDER", "gemini")
    ).strip().lower()
    if provider != "apicep":
        raise HTTPException(
            status_code=400,
            detail="La lectura automática de comprobantes no está activada.",
        )
    validation_enabled = (
        await get_setting_value(db, "RECEIPT_VALIDATION_ENABLED", "false")
    ).lower() == "true"
    if not validation_enabled:
        raise HTTPException(
            status_code=400,
            detail="La lectura automática de comprobantes no está activada.",
        )
    if not (await get_setting_value(db, "APICEP_API_KEY", "")).strip():
        gemini_key = (
            await get_setting_value(db, "GEMINI_API_KEY", "")
        ).strip()
        if not gemini_key:
            raise HTTPException(
                status_code=400,
                detail="La validación automática no está configurada.",
            )

    accounts = await _transfer_receiver_accounts(db)
    expected_recipient = " o ".join(
        f"{account['clabe']} {account.get('holder') or ''}".strip()
        for account in accounts
    )
    receiver_bank = accounts[0]["bank_code"]

    try:
        file_url = await save_document(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = await create_and_validate(
        db,
        "order_transfer",
        order.id,
        file_url,
        TRANSFER_RECEIPT,
        expected_amount=order.total_to_pay,
        expected_date=order.placed_at or datetime.now(timezone.utc),
        expected_recipient=expected_recipient,
    )

    if record.status == "preapproved":
        matched = _match_receiver_account(record.extracted or {}, accounts)
        if matched:
            order.cep_receiver_bank = matched["bank_code"]
        await apply_preapproved_transfer(db, record, actor_id=current_user.id)
        await db.commit()
        if (record.extracted or {}).get("_same_bank"):
            schedule_admin_transfer_review(
                str(order.id),
                order.total_to_pay,
                current_user.name,
                "Mismo banco: verifica el ingreso en tu estado de cuenta.",
            )
        return {
            "payment_status": "approved",
            "cep_status": "preapproved",
            "message": (
                "Pago preaprobado. El negocio ya puede preparar tu pedido; "
                "a las 9:30 se confirmará con Banxico."
            ),
        }

    if record.status == "pending_cep":
        order.cep_status = "pending_cep"
        await db.commit()
        return {
            "payment_status": "pending",
            "cep_status": "pending_cep",
            "message": record.summary or (
                "Tu comprobante quedó pendiente. Banxico valida de 09:30 a 23:00; "
                "lo validaremos automáticamente al abrir."
            ),
        }

    if record.status == "review":
        order.cep_status = "review"
        await db.commit()
        reason = record.summary or "Pago en revisión."
        issues = record.issues or []
        if issues:
            reason = f"{reason} {issues[0]}"
        schedule_admin_transfer_review(
            str(order.id), order.total_to_pay, current_user.name, reason
        )
        try:
            timeout_min = int(
                await get_setting_value(db, "RECEIPT_REVIEW_TIMEOUT_MIN", "30")
            )
        except (TypeError, ValueError):
            timeout_min = 30
        return {
            "payment_status": "pending",
            "cep_status": "review",
            "message": (
                "Tu pedido quedó en revisión de pago. "
                "El administrador debe confirmar tu transferencia. "
                f"Si no se confirma en los próximos {timeout_min} minutos, "
                "el pedido se cancelará y no se te cobrará."
            ),
        }

    if record.status != "high":
        order.cep_status = "review"
        await db.commit()
        issues = record.issues or []
        detail = record.error or (str(issues[0]) if issues else "")
        raise HTTPException(
            status_code=422,
            detail=detail
            or "No se pudo confirmar la transferencia con Banxico. "
            "Revisa que el comprobante sea legible o captura la clave de rastreo.",
        )

    extracted = record.extracted or {}
    validation = extracted.get("validation") or {}
    details = validation.get("cepDetails") or {}
    key = (
        str(extracted.get("trackingKey") or details.get("trackingKey") or "").strip()
    )
    if not key:
        raise HTTPException(
            status_code=422,
            detail=(
                "No se pudo leer la clave de rastreo del comprobante. "
                "Captúrala manualmente para validar tu pago."
            ),
        )
    sender_bank = extracted.get("senderBank") or details.get("senderBank")
    actual_receiver = details.get("receiverBank") or extracted.get("receiverBank")
    receiver_bank = _cep_code_for_bank_name(actual_receiver) or receiver_bank

    await _apply_cep_payment(
        db,
        order,
        current_user,
        tracking_key=key,
        sender_bank=sender_bank,
        receiver_bank=receiver_bank,
        cep_payload=extracted,
    )
    return {
        "payment_status": "approved",
        "cep_status": "valid",
        "message": "Pago validado por Banxico. El negocio ya puede preparar tu pedido.",
    }


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
    if order.near_closing:
        if body.status not in ("confirmed", "preparing"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Confirma si aceptas el pedido cerca del cierre. "
                    "Si no lo aceptas, cancélalo."
                ),
            )
        order.near_closing = False
        order.business_confirmation_deadline = None

    requested = body.status
    if (
        order.payment_method == "transfer"
        and order.payment_status != "approved"
        and requested in ("confirmed", "preparing", "ready")
        and not current_user.is_superuser
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "El pago por transferencia aún no está confirmado. "
                "No prepares el pedido hasta que se valide."
            ),
        )
    if restaurant is None:
        restaurant = await db.get(Restaurant, order.restaurant_id)
    try:
        await enforce_scheduled_rules(
            db,
            order,
            restaurant,
            requested,
            accept_early_prep=body.accept_early_prep,
        )
    except ScheduledOrderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if (
        requested == "confirmed"
        and order.requires_courier_approval
        and order.delivery_mode == "platform"
    ):
        requested = "preparing" if order.delivery_person_id else "awaiting_courier"

    try:
        await enforce_scheduled_rules(
            db,
            order,
            restaurant,
            requested,
            accept_early_prep=body.accept_early_prep,
        )
    except ScheduledOrderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

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
    elif requested == "ready":
        order.ready_at = now
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
    elif final_status in ("confirmed", "preparing"):
        if order.delivery_person_id:
            schedule_courier_preparing(str(order.id))
        elif order.delivery_mode == "platform":
            schedule_available_order(str(order.id), False)
    elif final_status == "ready":
        if order.delivery_person_id:
            schedule_courier_ready(str(order.id))
        elif order.delivery_mode == "platform":
            schedule_available_order(str(order.id), True)
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
