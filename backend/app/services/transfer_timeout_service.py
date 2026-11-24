"""Cancela pedidos por transferencia que no se confirmaron a tiempo."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.db.session import async_session
from app.models.order import Order
from app.models.receipt_validation import ReceiptValidation
from app.services.order_service import get_setting_value
from app.services.order_transfer_service import (
    cancel_unpaid_transfer,
    charge_failed_transfer,
)

logger = logging.getLogger(__name__)


async def expire_unpaid_transfer_orders(limit: int = 20) -> int:
    async with async_session() as db:
        try:
            timeout_min = int(
                await get_setting_value(db, "RECEIPT_REVIEW_TIMEOUT_MIN", "30")
            )
        except (TypeError, ValueError):
            timeout_min = 30
        if timeout_min <= 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_min)
        result = await db.execute(
            select(Order)
            .where(
                Order.payment_method == "transfer",
                Order.payment_status != "approved",
                Order.status == "pending",
                Order.created_at <= cutoff,
                or_(
                    Order.cep_status.is_(None),
                    Order.cep_status != "pending_cep",
                ),
            )
            .order_by(Order.created_at)
            .limit(limit)
        )
        orders = list(result.scalars().all())
        processed = 0
        for order in orders:
            record = await db.scalar(
                select(ReceiptValidation)
                .where(
                    ReceiptValidation.entity_type == "order_transfer",
                    ReceiptValidation.entity_id == order.id,
                )
                .order_by(ReceiptValidation.created_at.desc())
                .limit(1)
            )
            if record and record.status not in ("approved", "high", "preapproved"):
                await charge_failed_transfer(
                    db,
                    record,
                    "No se confirmó el pago dentro del tiempo de revisión.",
                )
                await db.commit()
            else:
                await cancel_unpaid_transfer(
                    db,
                    order,
                    "No se confirmó el pago por transferencia a tiempo.",
                )
            processed += 1
        return processed


async def transfer_timeout_loop(interval_seconds: int = 5 * 60) -> None:
    while True:
        try:
            await expire_unpaid_transfer_orders()
        except Exception:
            logger.exception("Falló la expiración de pedidos por transferencia")
        await asyncio.sleep(interval_seconds)
