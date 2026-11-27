"""Recargas: flujo manual mientras se integra un proveedor."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.recarga_order import RecargaOrder
from app.models.user import User
from app.services import recarga_ticket_service, sivetel_service
from app.services.order_service import get_setting_value

logger = logging.getLogger(__name__)

RECARGA_FEE = Decimal("2.00")
CHECKOUT_RECHARGE_FEE = Decimal("2.00")
MIN_RECHARGE = Decimal("10.00")
MAX_RECHARGE = Decimal("5000.00")
CASH_METHODS = {"cash"}

PROVIDER_MAX_ATTEMPTS = 8
PROCESSING_STALE_MINUTES = 10
INTERMITTENT_ERRORS = {
    0, 10, 20, 28, 97, 429, 500, 502, 503, 504, 6050, 6089, 9081,
}
DEFINITIVE_ERRORS = {2, 3, 4, 5, 11, 12, 21, 25, 40, 55, 91, 8090}


async def recharges_enabled(db: AsyncSession) -> bool:
    value = await get_setting_value(db, "RECHARGES_ENABLED", "false")
    return str(value).strip().lower() == "true"


def _now():
    return datetime.now(timezone.utc)


def normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) != 10:
        raise ValueError("Escribe un número de teléfono de 10 dígitos")
    return digits


def _apply_cash_accounting(dp: DeliveryPerson, recarga: RecargaOrder) -> None:
    if recarga.origin == "checkout":
        # En las recargas agregadas al pedido, el efectivo se liquida junto
        # con el total del pedido; no se abona comisión al repartidor.
        return
    if recarga.payment_method not in CASH_METHODS:
        return
    if recarga.payment_status != "paid":
        return
    if not recarga.debt_applied:
        dp.pending_platform_debt = (dp.pending_platform_debt or Decimal("0")) + recarga.amount
        recarga.debt_applied = True
    if not recarga.credit_applied and (recarga.fee or Decimal("0")) > 0:
        dp.pending_platform_credit = (dp.pending_platform_credit or Decimal("0")) + recarga.fee
        recarga.credit_applied = True


def _reverse_cash_accounting(dp: DeliveryPerson, recarga: RecargaOrder) -> None:
    if recarga.debt_applied:
        dp.pending_platform_debt = (dp.pending_platform_debt or Decimal("0")) - recarga.amount
        recarga.debt_applied = False
    if recarga.credit_applied:
        dp.pending_platform_credit = (dp.pending_platform_credit or Decimal("0")) - (recarga.fee or Decimal("0"))
        recarga.credit_applied = False


async def create_cash_recarga(
    db: AsyncSession,
    dp: DeliveryPerson,
    *,
    company: str,
    phone: str,
    amount: Decimal,
    order: Order | None = None,
    customer_name: str | None = None,
    product_code: str | None = None,
    product_description: str | None = None,
    product_kind: str | None = None,
) -> RecargaOrder:
    phone = normalize_phone(phone)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValueError("Escribe un monto válido")
    if order is not None and order.delivery_person_id != dp.id:
        raise ValueError("El pedido no está asignado a este repartidor")

    recarga = RecargaOrder(
        user_id=order.user_id if order else None,
        customer_name=(customer_name or "").strip() or None,
        delivery_person_id=dp.id,
        order_id=order.id if order else None,
        origin="courier",
        company=company.strip(),
        product_code=product_code,
        product_description=product_description,
        product_kind=product_kind,
        phone=phone,
        amount=amount,
        fee=RECARGA_FEE,
        total=amount + RECARGA_FEE,
        payment_method="cash",
        payment_status="paid",
        status="pending",
        paid_at=_now(),
    )
    _apply_cash_accounting(dp, recarga)
    db.add(recarga)
    await db.commit()
    await db.refresh(recarga)
    return recarga


async def create_transfer_recarga(
    db: AsyncSession,
    user: User,
    *,
    company: str,
    phone: str,
    amount: Decimal,
    customer_name: str | None = None,
    product_code: str | None = None,
    product_description: str | None = None,
    product_kind: str | None = None,
) -> RecargaOrder:
    phone = normalize_phone(phone)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValueError("Escribe un monto válido")
    recarga = RecargaOrder(
        user_id=user.id,
        customer_name=(customer_name or user.name or "").strip() or None,
        origin="portal",
        company=company.strip(),
        product_code=product_code,
        product_description=product_description,
        product_kind=product_kind,
        phone=phone,
        amount=amount,
        fee=Decimal("0"),
        total=amount,
        payment_method="transfer",
        payment_status="pending",
        status="requested",
    )
    db.add(recarga)
    await db.commit()
    await db.refresh(recarga)
    return recarga


async def list_recargas_for_courier(db: AsyncSession, dp: DeliveryPerson, limit: int = 50):
    result = await db.execute(
        select(RecargaOrder)
        .where(RecargaOrder.delivery_person_id == dp.id)
        .order_by(RecargaOrder.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_recargas_for_user(db: AsyncSession, user_id, limit: int = 50):
    result = await db.execute(
        select(RecargaOrder)
        .where(RecargaOrder.user_id == user_id)
        .order_by(RecargaOrder.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_recarga(db: AsyncSession, recarga_id) -> RecargaOrder | None:
    return await db.get(RecargaOrder, recarga_id)


async def confirm_transfer_payment(db: AsyncSession, recarga: RecargaOrder) -> RecargaOrder:
    if recarga.payment_method != "transfer":
        raise ValueError("Esta recarga no es por transferencia")
    if recarga.payment_status == "paid":
        return recarga
    recarga.payment_status = "paid"
    recarga.paid_at = _now()
    if recarga.status == "requested":
        recarga.status = "pending"
    await db.commit()
    await db.refresh(recarga)
    return recarga


def apply_transfer_payment(
    recarga: RecargaOrder,
    *,
    tracking_key: str | None,
    sender_bank: str | None,
    receiver_bank: str | None,
    payload: dict | None = None,
    cep_status: str = "valid",
) -> None:
    """Marca una recarga por transferencia como pagada."""
    if tracking_key:
        recarga.transfer_tracking_key = tracking_key
    recarga.cep_status = cep_status
    recarga.cep_validated_at = _now()
    recarga.cep_sender_bank = sender_bank
    recarga.cep_receiver_bank = receiver_bank
    if payload is not None:
        recarga.cep_payload = payload
    recarga.payment_status = "paid"
    recarga.paid_at = _now()
    if recarga.status == "requested":
        recarga.status = "pending"


async def settle_transfer_receipt(
    db: AsyncSession, record, *, approved: bool = True
) -> RecargaOrder | None:
    """Aplica la decisión de un comprobante de recarga (admin o reintento)."""
    recarga = await db.get(RecargaOrder, record.entity_id)
    if recarga is None:
        return None
    if not approved:
        recarga.cep_status = "rejected"
        return recarga
    if recarga.payment_status == "paid":
        return recarga
    extracted = record.extracted or {}
    details = (extracted.get("validation") or {}).get("cepDetails") or {}
    key = str(
        extracted.get("trackingKey") or details.get("trackingKey") or ""
    ).strip()
    apply_transfer_payment(
        recarga,
        tracking_key=key or None,
        sender_bank=extracted.get("senderBank") or details.get("senderBank"),
        receiver_bank=(
            details.get("receiverBank") or extracted.get("receiverBank")
        ),
        payload=extracted,
        cep_status=(
            "preapproved"
            if getattr(record, "status", "") == "preapproved"
            else "valid"
        ),
    )
    return recarga


async def complete_recarga(
    db: AsyncSession,
    recarga: RecargaOrder,
    reference: str | None = None,
    notes: str | None = None,
) -> RecargaOrder:
    if recarga.status in ("completed", "refunded"):
        raise ValueError("La recarga ya está cerrada")
    recarga.status = "completed"
    recarga.completed_at = _now()
    recarga.provider_reference = (reference or "").strip() or recarga.provider_reference
    if notes:
        recarga.notes = notes
    if recarga.order_id:
        order = await db.get(Order, recarga.order_id)
        if order is not None and (order.recharge_amount or 0) > 0:
            order.recharge_status = "completed"
    await db.commit()
    await db.refresh(recarga)
    await _send_completion_ticket(db, recarga)
    return recarga


async def fail_recarga(
    db: AsyncSession,
    recarga: RecargaOrder,
    dp: DeliveryPerson | None,
    *,
    refund: bool = True,
    error_message: str | None = None,
) -> RecargaOrder:
    if recarga.status == "completed":
        raise ValueError("La recarga ya se completó")
    if error_message:
        recarga.error_message = error_message
    if refund and recarga.payment_status == "paid":
        if dp is None and recarga.delivery_person_id:
            dp = await db.get(DeliveryPerson, recarga.delivery_person_id)
        if dp is not None:
            _reverse_cash_accounting(dp, recarga)
        recarga.payment_status = "refunded"
        recarga.refunded_at = _now()
        recarga.status = "refunded"
    else:
        recarga.status = "failed"
    await db.commit()
    await db.refresh(recarga)
    return recarga


async def retry_recarga(db: AsyncSession, recarga: RecargaOrder) -> RecargaOrder:
    if recarga.status not in ("failed",):
        raise ValueError("Solo se pueden reintentar recargas fallidas")
    if recarga.payment_status != "paid" and recarga.payment_method == "cash":
        raise ValueError("La recarga no tiene pago registrado")
    recarga.status = "pending"
    recarga.error_message = None
    await db.commit()
    await db.refresh(recarga)
    return recarga


# ---------------------------------------------------------------------------
# Recargas agregadas al pedido
# ---------------------------------------------------------------------------

def checkout_fee(payment_method: str, amount: Decimal) -> Decimal:
    """Comisión de $2 solo cuando la recarga del pedido se paga en efectivo."""
    if Decimal(amount or 0) <= 0:
        return Decimal("0.00")
    return CHECKOUT_RECHARGE_FEE if payment_method == "cash" else Decimal("0.00")


async def get_checkout_recarga(
    db: AsyncSession, order_id
) -> RecargaOrder | None:
    return await db.scalar(
        select(RecargaOrder).where(
            RecargaOrder.order_id == order_id,
            RecargaOrder.origin == "checkout",
        )
    )


async def confirm_checkout_recharge(
    db: AsyncSession, order
) -> RecargaOrder | None:
    """Marca como pagada la recarga del pedido al confirmarse la transferencia."""
    recarga = await get_checkout_recarga(db, order.id)
    if recarga is None:
        return None
    if recarga.payment_status != "paid":
        recarga.payment_status = "paid"
        recarga.paid_at = _now()
    return recarga


async def attach_courier(
    db: AsyncSession, order, delivery_person_id
) -> RecargaOrder | None:
    """Asocia la recarga del pedido al repartidor que lo entrega."""
    recarga = await get_checkout_recarga(db, order.id)
    if recarga is not None and recarga.delivery_person_id is None:
        recarga.delivery_person_id = delivery_person_id
    return recarga


async def charge_cancelled_checkout_recharge(
    db: AsyncSession, order
) -> Decimal:
    """Al cancelar un pedido en efectivo, la recarga ya aplicada queda a saldo."""
    amount = Decimal(order.recharge_amount or 0)
    if amount <= 0 or order.recharge_status == "charged":
        return Decimal("0.00")

    customer = await db.get(User, order.user_id) if order.user_id else None
    if customer is not None:
        customer.pending_balance = (customer.pending_balance or Decimal("0")) + amount
    order.recharge_status = "charged"
    recarga = await get_checkout_recarga(db, order.id)
    if recarga is not None:
        recarga.notes = (
            "Pedido cancelado: el monto de la recarga se cargó al saldo del cliente."
        )
    return amount


async def cancel_pending_checkout_recharge(
    db: AsyncSession, order, reason: str
) -> RecargaOrder | None:
    """Cancela la recarga si el pedido se cancela antes de pagarla."""
    recarga = await get_checkout_recarga(db, order.id)
    if recarga is None:
        return None
    if recarga.payment_status != "paid":
        recarga.status = "cancelled"
        recarga.payment_status = "cancelled"
        recarga.notes = reason
    return recarga


async def checkout_recharge_was_paid(db: AsyncSession, order) -> bool:
    recarga = await get_checkout_recarga(db, order.id)
    return bool(recarga and recarga.payment_status == "paid")


# ---------------------------------------------------------------------------
# Procesamiento automático con Sivetel
# ---------------------------------------------------------------------------

def _error_parts(body: dict) -> tuple[int, str]:
    try:
        code = int(body.get("error") or 0)
    except (TypeError, ValueError):
        code = 0
    return code, str(body.get("message") or "Error de Sivetel")


async def _send_completion_ticket(
    db: AsyncSession, recarga: RecargaOrder
) -> None:
    try:
        await recarga_ticket_service.send_recarga_ticket(db, recarga)
    except Exception:
        logger.exception("No se pudo enviar el ticket de la recarga %s", recarga.id)


async def _mark_completed(
    db: AsyncSession, recarga: RecargaOrder, body: dict
) -> None:
    data = body.get("data") or {}
    folio = ""
    if isinstance(data, dict):
        folio = str(data.get("folio") or "").strip()
    recarga.status = "completed"
    recarga.completed_at = _now()
    recarga.provider_folio = folio or recarga.provider_folio
    recarga.provider_reference = (
        folio or recarga.provider_request_id or recarga.provider_reference
    )
    recarga.error_message = None
    if recarga.order_id:
        order = await db.get(Order, recarga.order_id)
        if order is not None and (order.recharge_amount or 0) > 0:
            order.recharge_status = "completed"
    logger.info("Recarga %s completada. Folio: %s", recarga.id, folio or "—")


async def _mark_failed(
    db: AsyncSession, recarga: RecargaOrder, code: int, message: str
) -> None:
    recarga.status = "failed"
    recarga.error_message = f"{message} (código {code})" if code else message
    logger.warning(
        "Recarga %s falló con Sivetel: %s (código %s)",
        recarga.id,
        message,
        code,
    )


async def process_recarga_with_sivetel(
    db: AsyncSession, recarga: RecargaOrder
) -> str:
    """Procesa una recarga con Sivetel. Devuelve completed/failed/retry/disabled."""
    if recarga.status in ("completed", "refunded", "cancelled"):
        return "closed"
    config = await sivetel_service.load_config(db)
    if config is None:
        return "disabled"

    client = sivetel_service.SivetelClient(config)
    recarga.status = "processing"
    recarga.provider_attempts = (recarga.provider_attempts or 0) + 1
    recarga.last_attempt_at = _now()
    attempts = recarga.provider_attempts
    await db.commit()

    try:
        body: dict | None = None
        if recarga.provider_request_id:
            body = await client.consultar(recarga.provider_request_id)
            if body.get("status"):
                await _mark_completed(db, recarga, body)
                await db.commit()
                await _send_completion_ticket(db, recarga)
                return "completed"
            code, message = _error_parts(body)
            if code == 414:
                # Reservada pero aún no procesada: se procesa con el mismo id.
                body = await client.procesar(recarga.provider_request_id)
            elif code == 415:
                # El requestid ya no existe: se reserva de nuevo.
                recarga.provider_request_id = None
                body = None
            elif code == 413:
                # Ya procesada: se consulta de nuevo para recuperar el resultado.
                body = await client.consultar(recarga.provider_request_id)
            else:
                raise sivetel_service.SivetelError(code, message)

        if body is None and not recarga.provider_request_id:
            product = recarga.product_code or await sivetel_service.resolver_producto(
                client, recarga.company, recarga.amount
            )
            request_id = await client.reservar(recarga.phone, product)
            recarga.provider_request_id = request_id
            recarga.provider_reference = request_id
            await db.commit()
            body = await client.procesar(request_id)

        if body is None:
            raise sivetel_service.SivetelError(0, "Sin respuesta de Sivetel")

        if body.get("status"):
            await _mark_completed(db, recarga, body)
            await db.commit()
            await _send_completion_ticket(db, recarga)
            return "completed"

        code, message = _error_parts(body)

        # 413: otra llamada ya la procesó; se recupera el resultado.
        if code == 413 and recarga.provider_request_id:
            retry_body = await client.consultar(recarga.provider_request_id)
            if retry_body.get("status"):
                await _mark_completed(db, recarga, retry_body)
                await db.commit()
                await _send_completion_ticket(db, recarga)
                return "completed"
            code, message = _error_parts(retry_body)

        if code in INTERMITTENT_ERRORS or code == 414:
            recarga.status = "pending"
            recarga.error_message = message
            if attempts >= PROVIDER_MAX_ATTEMPTS:
                await _mark_failed(db, recarga, code, message)
                await db.commit()
                return "failed"
            await db.commit()
            return "retry"

        await _mark_failed(db, recarga, code, message)
        await db.commit()
        return "failed"

    except sivetel_service.SivetelError as exc:
        if exc.code in INTERMITTENT_ERRORS or exc.code == 0:
            recarga.status = "pending"
            recarga.error_message = exc.message
            if attempts >= PROVIDER_MAX_ATTEMPTS:
                await _mark_failed(db, recarga, exc.code, exc.message)
                await db.commit()
                return "failed"
            await db.commit()
            return "retry"
        await _mark_failed(db, recarga, exc.code, exc.message)
        await db.commit()
        return "failed"
    except Exception:
        await db.rollback()
        logger.exception("Error inesperado procesando recarga %s", recarga.id)
        raise


async def process_pending_recargas(limit: int = 8) -> int:
    """Procesa recargas pagadas pendientes. Pensado para el loop de fondo."""
    cutoff = _now() - timedelta(minutes=PROCESSING_STALE_MINUTES)
    async with async_session() as db:
        if await sivetel_service.load_config(db) is None:
            return 0
        ids = (
            await db.execute(
                select(RecargaOrder.id)
                .where(
                    RecargaOrder.payment_status == "paid",
                    RecargaOrder.amount > 0,
                    or_(
                        RecargaOrder.status == "pending",
                        and_(
                            RecargaOrder.status == "processing",
                            RecargaOrder.last_attempt_at <= cutoff,
                        ),
                    ),
                )
                .order_by(RecargaOrder.created_at)
                .limit(limit)
            )
        ).scalars().all()

    processed = 0
    for recarga_id in ids:
        async with async_session() as db:
            recarga = await db.get(RecargaOrder, recarga_id)
            if recarga is None:
                continue
            try:
                await process_recarga_with_sivetel(db, recarga)
                processed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                await db.rollback()
                logger.exception("No se pudo procesar la recarga %s", recarga_id)
        await asyncio.sleep(0.3)
    return processed


async def recarga_processing_loop() -> None:
    """Revisa cada minuto las recargas pendientes de enviar a Sivetel."""
    while True:
        try:
            await process_pending_recargas()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error en el loop de recargas")
        await asyncio.sleep(60)
