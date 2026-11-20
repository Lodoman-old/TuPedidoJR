"""Validación de comprobantes de reservas de renta."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.db.session import async_session
from app.models.rental_booking import RentalBooking
from app.services.receipt_validation_service import TRANSFER, create_and_validate

logger = logging.getLogger(__name__)


async def _run_validation(booking_id: str) -> None:
    async with async_session() as db:
        booking = await db.get(RentalBooking, booking_id)
        if not booking or not booking.proof_url:
            return
        try:
            record = await create_and_validate(
                db,
                "rental_payment",
                booking.id,
                booking.proof_url,
                TRANSFER,
                booking.online_amount,
                datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("No se pudo validar el comprobante de renta %s", booking_id)
            record = None

        if record is not None:
            booking.receipt_status = "approved" if record.status == "high" else "review"
            if record.status == "high":
                booking.payment_status = (
                    "paid" if booking.payment_mode == "full" else "deposit_paid"
                )
                booking.paid_at = datetime.now(timezone.utc)
            else:
                booking.payment_status = "proof_review"
        else:
            booking.receipt_status = "review"
            booking.payment_status = "proof_review"
        await db.commit()


def schedule_rental_validation(booking_id: str) -> None:
    try:
        asyncio.create_task(_run_validation(str(booking_id)))
    except RuntimeError:
        logger.debug("No event loop for rental validation")
