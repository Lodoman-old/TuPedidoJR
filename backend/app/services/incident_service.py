"""Incidencias de entrega y política de certeza.

Reglas:
- El repartidor cobra su viaje completo aunque no se entregue, salvo que la
  falla sea comprobadamente su culpa.
- El negocio cobra el producto cuando se pierde, se daña o se desecha.
- Si el producto se recupera (se devuelve al negocio), no se paga el producto.
- Al cliente no se le reembolsa en comida. En no perecedero pagado y devuelto
  se le reembolsa el producto, descontando el envío.
- El cliente que no pagó y no recibió queda debiendo el total en comida.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery_incident import DeliveryIncident
from app.models.delivery_person import DeliveryPerson
from app.models.mandado import Mandado
from app.models.order import Order
from app.models.restaurant_adjustment import RestaurantAdjustment
from app.models.shipment import Shipment
from app.models.user import User
from app.services.order_service import get_setting_value
from app.services import recarga_service
from app.services.push_service import (
    schedule_mandado_status,
    schedule_order_status,
    schedule_shipment_status,
)
from app.services.rounding import round_half_down

REASON_LABELS = {
    "customer_unreachable": "Cliente no contesta",
    "wrong_address": "Dirección incorrecta",
    "customer_refused": "Cliente rechazó el pedido",
    "business_closed": "Negocio cerrado",
    "damaged": "Producto dañado",
    "other": "Otro",
}

STATUS_LABELS = {
    "reported": "Reportada",
    "in_custody": "En resguardo",
    "redelivery": "Reentrega programada",
    "returned": "Devuelta al negocio",
    "discarded": "Desechada",
    "authorization": "Por autorizar",
    "resolved": "Resuelta",
}

FOOD_RETRY_MIN = "FAILED_FOOD_RETRY_MIN"
CUSTODY_HOURS = "CUSTODY_HOURS"
REDELIVERY_FEE = "REDELIVERY_FEE"
INCIDENT_AUTH_LIMIT = "INCIDENT_AUTHORIZATION_LIMIT"


async def _setting_decimal(db: AsyncSession, key: str, default: str) -> Decimal:
    try:
        return Decimal(str(await get_setting_value(db, key, default)))
    except Exception:
        return Decimal(default)


async def _setting_int(db: AsyncSession, key: str, default: str) -> int:
    try:
        return int(await get_setting_value(db, key, default))
    except Exception:
        return int(default)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


async def _pay_courier(db: AsyncSession, incident: DeliveryIncident, amount: Decimal) -> None:
    if amount <= 0:
        incident.courier_pay = Decimal("0")
        return
    dp = await db.get(DeliveryPerson, incident.courier_id) if incident.courier_id else None
    if dp:
        dp.pending_platform_credit = round_half_down(
            (dp.pending_platform_credit or Decimal("0")) + amount
        )
    incident.courier_pay = round_half_down(amount)


async def _pay_business(db: AsyncSession, incident: DeliveryIncident, amount: Decimal) -> None:
    if amount <= 0:
        incident.business_pay = Decimal("0")
        return
    if incident.restaurant_id:
        db.add(RestaurantAdjustment(
            id=uuid.uuid4(),
            restaurant_id=incident.restaurant_id,
            incident_id=incident.id,
            kind="credit",
            amount=round_half_down(amount),
            description="Cobertura de incidencia de entrega",
        ))
    incident.business_pay = round_half_down(amount)


async def _charge_customer(db: AsyncSession, incident: DeliveryIncident, amount: Decimal) -> None:
    if amount <= 0:
        incident.customer_debt = Decimal("0")
        return
    customer = await db.get(User, incident.customer_id) if incident.customer_id else None
    if customer:
        customer.pending_balance = round_half_down(
            (customer.pending_balance or Decimal("0")) + amount
        )
    incident.customer_debt = round_half_down(amount)


async def _refund_customer(db: AsyncSession, incident: DeliveryIncident, amount: Decimal) -> None:
    if amount <= 0:
        incident.customer_refund = Decimal("0")
        return
    order = await db.get(Order, incident.entity_id) if incident.entity_type == "order" else None
    if order:
        order.refund_amount = round_half_down((order.refund_amount or Decimal("0")) + amount)
        order.refund_status = "pending"
    incident.customer_refund = round_half_down(amount)


def _platform_cost(incident: DeliveryIncident) -> Decimal:
    cost = (incident.courier_pay or Decimal("0")) + (incident.business_pay or Decimal("0"))
    cost -= incident.customer_debt or Decimal("0")
    return round_half_down(max(cost, Decimal("0")))


async def _create(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id,
    item_kind: str,
    courier: DeliveryPerson,
    reason_code: str,
    notes: str | None,
    photo_url: str | None,
    lat,
    lng,
    product_amount: Decimal,
    delivery_amount: Decimal,
    restaurant_id=None,
    customer_id=None,
) -> DeliveryIncident:
    incident = DeliveryIncident(
        id=uuid.uuid4(),
        entity_type=entity_type,
        entity_id=entity_id,
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        courier_id=courier.id,
        reason_code=reason_code,
        notes=(notes or "").strip() or None,
        photo_url=photo_url,
        lat=lat,
        lng=lng,
        item_kind=item_kind,
        status="reported",
        product_amount=round_half_down(product_amount or Decimal("0")),
        delivery_amount=round_half_down(delivery_amount or Decimal("0")),
    )
    db.add(incident)
    return incident


async def report_order_failure(
    db: AsyncSession,
    order: Order,
    courier: DeliveryPerson,
    reason_code: str,
    notes: str | None,
    photo_url: str | None,
    lat=None,
    lng=None,
) -> DeliveryIncident:
    incident = await _create(
        db,
        entity_type="order",
        entity_id=order.id,
        item_kind="food",
        courier=courier,
        reason_code=reason_code,
        notes=notes,
        photo_url=photo_url,
        lat=lat,
        lng=lng,
        product_amount=order.subtotal or Decimal("0"),
        delivery_amount=order.delivery_earnings or Decimal("0"),
        restaurant_id=order.restaurant_id,
        customer_id=order.user_id,
    )
    order.status = "delivery_failed"
    order.incident_id = incident.id
    if courier.current_order_id == order.id:
        courier.current_order_id = None
    return incident


async def report_mandado_failure(
    db: AsyncSession,
    mandado: Mandado,
    courier: DeliveryPerson,
    reason_code: str,
    notes: str | None,
    photo_url: str | None,
    lat=None,
    lng=None,
) -> DeliveryIncident:
    incident = await _create(
        db,
        entity_type="mandado",
        entity_id=mandado.id,
        item_kind="goods",
        courier=courier,
        reason_code=reason_code,
        notes=notes,
        photo_url=photo_url,
        lat=lat,
        lng=lng,
        product_amount=mandado.product_total or mandado.estimated_budget or Decimal("0"),
        delivery_amount=mandado.delivery_fee or Decimal("0"),
        customer_id=mandado.user_id,
    )
    mandado.status = "delivery_failed"
    return incident


async def report_shipment_failure(
    db: AsyncSession,
    shipment: Shipment,
    courier: DeliveryPerson,
    reason_code: str,
    notes: str | None,
    photo_url: str | None,
    lat=None,
    lng=None,
) -> DeliveryIncident:
    incident = await _create(
        db,
        entity_type="shipment",
        entity_id=shipment.id,
        item_kind="package",
        courier=courier,
        reason_code=reason_code,
        notes=notes,
        photo_url=photo_url,
        lat=lat,
        lng=lng,
        product_amount=shipment.declared_value or shipment.collect_amount or Decimal("0"),
        delivery_amount=shipment.delivery_fee or Decimal("0"),
        restaurant_id=shipment.store_id,
    )
    shipment.status = "failed"
    shipment.failure_reason = REASON_LABELS.get(reason_code, reason_code)
    shipment.return_fee = Decimal("0")
    shipment.courier_earnings = Decimal("0")
    shipment.store_charge = Decimal("0")
    shipment.cod_status = "not_required"
    return incident


async def mark_custody(
    db: AsyncSession,
    incident: DeliveryIncident,
    photo_url: str | None = None,
) -> DeliveryIncident:
    if incident.status not in ("reported", "authorization"):
        raise ValueError("La incidencia ya no se puede resguardar")
    incident.status = "in_custody"
    incident.custody_code = _code()
    incident.custody_at = _now()
    incident.custody_photo_url = photo_url
    hours = await _setting_int(db, CUSTODY_HOURS, "48")
    incident.holding_until = _now() + timedelta(hours=max(hours, 1))
    await _pay_courier(db, incident, incident.delivery_amount)
    return incident


async def schedule_redelivery(
    db: AsyncSession,
    incident: DeliveryIncident,
    fee: Decimal | None = None,
) -> DeliveryIncident:
    if incident.status not in ("reported", "in_custody", "authorization"):
        raise ValueError("La incidencia ya no se puede reenviar")
    if fee is None:
        fee = await _setting_decimal(db, REDELIVERY_FEE, "15")
    fee = round_half_down(max(fee, Decimal("0")))

    incident.status = "redelivery"
    incident.redelivery_at = _now()
    incident.redelivery_fee = fee
    incident.resolved_at = _now()
    await _pay_courier(db, incident, incident.delivery_amount)

    if incident.entity_type == "order":
        order = await db.get(Order, incident.entity_id)
        if order:
            order.status = "awaiting_courier"
            order.delivery_person_id = None
            order.total = round_half_down((order.total or Decimal("0")) + fee)
            order.redelivery_fee = round_half_down((order.redelivery_fee or Decimal("0")) + fee)
            schedule_order_status(str(order.id), "awaiting_courier")
    elif incident.entity_type == "mandado":
        mandado = await db.get(Mandado, incident.entity_id)
        if mandado:
            mandado.status = "pending"
            mandado.delivery_person_id = None
            mandado.platform_fee = round_half_down((mandado.platform_fee or Decimal("0")) + fee)
            schedule_mandado_status(str(mandado.id), "pending")
    elif incident.entity_type == "shipment":
        shipment = await db.get(Shipment, incident.entity_id)
        if shipment:
            shipment.status = "pending"
            shipment.delivery_person_id = None
            if (shipment.amount_to_collect or Decimal("0")) > 0:
                shipment.amount_to_collect = round_half_down(
                    (shipment.amount_to_collect or Decimal("0")) + fee
                )
            else:
                shipment.store_charge = round_half_down(
                    (shipment.store_charge or Decimal("0")) + fee
                )
            schedule_shipment_status(str(shipment.id), "pending")
    return incident


async def return_to_business(
    db: AsyncSession,
    incident: DeliveryIncident,
    notes: str | None = None,
) -> DeliveryIncident:
    if incident.status not in ("reported", "in_custody", "authorization"):
        raise ValueError("La incidencia ya no se puede devolver")
    incident.status = "returned"
    incident.resolution_notes = (notes or "").strip() or None
    incident.resolved_at = _now()
    await _pay_courier(db, incident, incident.delivery_amount)

    if incident.entity_type == "order":
        order = await db.get(Order, incident.entity_id)
        if order:
            order.status = "cancelled"
            order.cancelled_at = _now()
            order.cancellation_reason = "Producto devuelto al negocio"
            if order.payment_method in ("transfer", "mp") and order.payment_status in ("approved", "paid"):
                # No perecedero pagado: se devuelve el producto, se descuenta el envío.
                # El monto de la recarga no se reembolsa porque ya se aplicó.
                await _refund_customer(db, incident, order.subtotal or Decimal("0"))
            elif order.payment_method == "cash" and (order.recharge_amount or 0) > 0:
                await recarga_service.charge_cancelled_checkout_recharge(db, order)
            elif (order.recharge_amount or 0) > 0:
                await recarga_service.cancel_pending_checkout_recharge(
                    db, order, "Pedido devuelto al negocio."
                )
            schedule_order_status(str(order.id), "cancelled")
    elif incident.entity_type == "mandado":
        mandado = await db.get(Mandado, incident.entity_id)
        if mandado:
            mandado.status = "cancelled"
            schedule_mandado_status(str(mandado.id), "cancelled")
    elif incident.entity_type == "shipment":
        shipment = await db.get(Shipment, incident.entity_id)
        if shipment:
            shipment.status = "failed"
            schedule_shipment_status(str(shipment.id), "failed")
    return incident


async def discard_item(
    db: AsyncSession,
    incident: DeliveryIncident,
    notes: str | None = None,
    photo_url: str | None = None,
    courier_fault: bool = False,
) -> DeliveryIncident:
    if incident.status not in ("reported", "in_custody", "authorization"):
        raise ValueError("La incidencia ya no se puede desechar")
    incident.status = "discarded"
    incident.resolution_notes = (notes or "").strip() or None
    if photo_url:
        incident.photo_url = photo_url
    incident.resolved_at = _now()

    limit = await _setting_decimal(db, INCIDENT_AUTH_LIMIT, "500")
    if courier_fault:
        await _pay_courier(db, incident, Decimal("0"))
        if (incident.product_amount or Decimal("0")) > limit:
            incident.status = "authorization"
            incident.requires_authorization = True
            return incident
    else:
        await _pay_courier(db, incident, incident.delivery_amount)

    await _pay_business(db, incident, incident.product_amount)
    if incident.entity_type == "order":
        order = await db.get(Order, incident.entity_id)
        if order and order.payment_method == "cash":
            # No pagó y no recibió: debe el total del pedido. Si la recarga
            # agregada al pedido ya se aplicó, también se le carga.
            amount = order.total or Decimal("0")
            if await recarga_service.checkout_recharge_was_paid(db, order):
                amount += order.recharge_amount or Decimal("0")
            await _charge_customer(db, incident, amount)
    elif incident.entity_type == "mandado":
        mandado = await db.get(Mandado, incident.entity_id)
        if mandado and mandado.payment_method == "cash" and not mandado.prepayment_required:
            await _charge_customer(db, incident, mandado.final_total or mandado.estimated_total or Decimal("0"))
    incident.platform_cost = _platform_cost(incident)
    return incident


async def authorize_incident(
    db: AsyncSession,
    incident: DeliveryIncident,
    admin_id,
    absorb: bool,
    notes: str | None = None,
) -> DeliveryIncident:
    if incident.status != "authorization":
        raise ValueError("La incidencia no requiere autorización")
    incident.approved_by = admin_id
    incident.approved_at = _now()
    incident.resolution_notes = (notes or "").strip() or None
    incident.status = "resolved"
    incident.resolved_at = _now()
    if absorb:
        await _pay_business(db, incident, incident.product_amount)
    else:
        dp = await db.get(DeliveryPerson, incident.courier_id) if incident.courier_id else None
        if dp:
            dp.pending_platform_debt = round_half_down(
                (dp.pending_platform_debt or Decimal("0")) + (incident.product_amount or Decimal("0"))
            )
        incident.business_pay = Decimal("0")
    incident.platform_cost = _platform_cost(incident)
    return incident


async def resolve_incident(
    db: AsyncSession,
    incident: DeliveryIncident,
    notes: str | None = None,
) -> DeliveryIncident:
    incident.status = "resolved"
    incident.resolved_at = _now()
    incident.resolution_notes = (notes or "").strip() or incident.resolution_notes
    return incident
