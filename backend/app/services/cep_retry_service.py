"""Reintenta validar con Banxico los comprobantes pendientes o preaprobados."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import async_session
from app.models.order import Order
from app.models.receipt_validation import ReceiptValidation
from app.models.user import User
from app.services.cep_validation_service import banxico_open
from app.services.order_service import get_setting_value
from app.services.order_transfer_service import (
    charge_failed_transfer,
    settle_order_transfer,
)
from app.services.push_service import notify_admin_transfer_review
from app.services.receipt_validation_service import revalidate_receipt

logger = logging.getLogger(__name__)


async def _order_info(db, record: ReceiptValidation):
    order = await db.get(Order, record.entity_id)
    if not order:
        return None, None, "Cliente"
    customer = await db.get(User, order.user_id) if order.user_id else None
    return order, customer, customer.name if customer else "Cliente"


async def _max_attempts(db) -> int:
    try:
        return max(
            int(await get_setting_value(db, "RECEIPT_CEP_RETRY_MAX_ATTEMPTS", "6")),
            1,
        )
    except (TypeError, ValueError):
        return 6


async def retry_pending_cep(limit: int = 20) -> int:
    """Reintenta los comprobantes que esperan confirmación de Banxico."""
    if not banxico_open():
        return 0

    processed = 0
    async with async_session() as db:
        configured_attempts = await _max_attempts(db)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        result = await db.execute(
            select(ReceiptValidation)
            .where(
                ReceiptValidation.entity_type == "order_transfer",
                ReceiptValidation.status.in_(("pending_cep", "preapproved")),
                ReceiptValidation.created_at >= cutoff,
            )
            .order_by(ReceiptValidation.created_at)
            .limit(limit * 3)
        )
        records = [
            record
            for record in result.scalars().all()
            if not (record.extracted or {}).get("_same_bank")
            and not (record.extracted or {}).get("_retry_disabled")
        ][:limit]

        for record in records:
            was_preapproved = record.status == "preapproved"
            extracted = dict(record.extracted or {})
            attempts = int(extracted.get("cep_retry_count") or 0)
            max_attempts = configured_attempts
            if was_preapproved:
                # Damos un margen corto antes de cargar al cliente.
                max_attempts = min(max_attempts, 2)

            order, _, customer_name = await _order_info(db, record)
            if not order:
                record.status = "review"
                record.summary = "El pedido ya no existe."
                await db.commit()
                continue

            if attempts >= max_attempts:
                if was_preapproved:
                    await charge_failed_transfer(
                        db,
                        record,
                        "Banxico no confirmó la transferencia después del margen.",
                    )
                    await db.commit()
                else:
                    record.status = "review"
                    record.summary = "Se agotaron los reintentos con Banxico."
                    record.extracted = extracted
                    await db.commit()
                    await notify_admin_transfer_review(
                        str(order.id),
                        order.total_to_pay,
                        customer_name,
                        "Se agotaron los reintentos con Banxico.",
                    )
                continue

            try:
                record = await revalidate_receipt(db, record)
            except Exception:
                logger.exception(
                    "Falló el reintento CEP del comprobante %s", record.id
                )
                continue

            processed += 1
            extracted = dict(record.extracted or {})

            if record.status == "high":
                await settle_order_transfer(db, record, True)
                await db.commit()
                continue

            if (record.extracted or {}).get("_same_bank"):
                extracted["_retry_disabled"] = True
                record.extracted = extracted
                if was_preapproved:
                    record.status = "preapproved"
                else:
                    record.status = "review"
                    record.summary = (
                        "Mismo banco: Banxico no emite CEP. Verifica el ingreso."
                    )
                await db.commit()
                if not was_preapproved:
                    await notify_admin_transfer_review(
                        str(order.id),
                        order.total_to_pay,
                        customer_name,
                        "Mismo banco: verifica el ingreso manualmente.",
                    )
                continue

            if record.status == "pending_cep":
                attempts += 1
                extracted["cep_retry_count"] = attempts
                record.status = "preapproved" if was_preapproved else "pending_cep"
                record.extracted = extracted
                record.summary = (
                    "Banxico todavía no confirma el pago. Se reintentará."
                )
                await db.commit()
                if attempts >= max_attempts:
                    if was_preapproved:
                        await charge_failed_transfer(
                            db,
                            record,
                            "Banxico no confirmó la transferencia.",
                        )
                        await db.commit()
                    else:
                        record.status = "review"
                        record.summary = "Se agotaron los reintentos con Banxico."
                        await db.commit()
                        await notify_admin_transfer_review(
                            str(order.id),
                            order.total_to_pay,
                            customer_name,
                            "Se agotaron los reintentos con Banxico.",
                        )
                continue

            if was_preapproved:
                # Gemini volvió a preaprobar: seguimos esperando a Banxico.
                if record.status == "preapproved":
                    attempts += 1
                    extracted["cep_retry_count"] = attempts
                    record.extracted = extracted
                    await db.commit()
                    continue

                attempts += 1
                extracted["cep_retry_count"] = attempts
                record.extracted = extracted
                if attempts >= max_attempts:
                    await charge_failed_transfer(
                        db,
                        record,
                        record.error
                        or record.summary
                        or "Banxico no confirmó la transferencia.",
                    )
                    await db.commit()
                else:
                    record.status = "preapproved"
                    record.summary = (
                        "Banxico aún no confirma. Se reintentará."
                    )
                    await db.commit()
                continue

            attempts += 1
            extracted["cep_retry_count"] = attempts
            if attempts >= max_attempts:
                record.status = "review"
                record.summary = "Se agotaron los reintentos con Banxico."
                record.extracted = extracted
                await db.commit()
                await notify_admin_transfer_review(
                    str(order.id),
                    order.total_to_pay,
                    customer_name,
                    "Se agotaron los reintentos con Banxico.",
                )
            else:
                record.status = "pending_cep"
                record.extracted = extracted
                record.summary = "Banxico aún no confirma el pago. Se reintentará."
                await db.commit()

    return processed


async def cep_retry_loop(interval_seconds: int = 15 * 60) -> None:
    while True:
        try:
            await retry_pending_cep()
        except Exception:
            logger.exception("Falló el reintento automático de CEP")
        sleep_for = interval_seconds
        try:
            async with async_session() as db:
                minutes = int(
                    await get_setting_value(
                        db, "RECEIPT_CEP_RETRY_INTERVAL_MIN", "15"
                    )
                )
                sleep_for = max(minutes * 60, 60)
        except (TypeError, ValueError):
            pass
        except Exception:
            logger.exception("No se pudo leer el intervalo de reintento CEP")
        await asyncio.sleep(sleep_for)
