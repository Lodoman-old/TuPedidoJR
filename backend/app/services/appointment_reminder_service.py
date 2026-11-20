"""Recordatorios de citas por push para clientes y negocios."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import async_session
from app.models.appointment import Appointment
from app.models.rental_booking import RentalBooking
from app.services.push_service import (
    schedule_appointment_business_now,
    schedule_appointment_client_reminder,
    schedule_rental_business_now,
    schedule_rental_client_reminder,
)

logger = logging.getLogger(__name__)


async def _send_due(db) -> int:
    now = datetime.now(timezone.utc)
    sent = 0

    client_rows = (await db.execute(
        select(Appointment).where(
            Appointment.status == "confirmed",
            Appointment.client_reminder_sent_at.is_(None),
            Appointment.start_at >= now + timedelta(minutes=25),
            Appointment.start_at <= now + timedelta(minutes=35),
        ).limit(100)
    )).scalars().all()
    for appointment in client_rows:
        appointment.client_reminder_sent_at = now
        schedule_appointment_client_reminder(str(appointment.id))
        sent += 1

    business_rows = (await db.execute(
        select(Appointment).where(
            Appointment.status == "confirmed",
            Appointment.business_reminder_sent_at.is_(None),
            Appointment.start_at >= now - timedelta(minutes=1),
            Appointment.start_at <= now + timedelta(minutes=4),
        ).limit(100)
    )).scalars().all()
    for appointment in business_rows:
        appointment.business_reminder_sent_at = now
        schedule_appointment_business_now(str(appointment.id))
        sent += 1

    rental_client_rows = (await db.execute(
        select(RentalBooking).where(
            RentalBooking.status == "confirmed",
            RentalBooking.client_reminder_sent_at.is_(None),
            RentalBooking.start_at >= now + timedelta(minutes=25),
            RentalBooking.start_at <= now + timedelta(minutes=35),
        ).limit(100)
    )).scalars().all()
    for booking in rental_client_rows:
        booking.client_reminder_sent_at = now
        schedule_rental_client_reminder(str(booking.id))
        sent += 1

    rental_business_rows = (await db.execute(
        select(RentalBooking).where(
            RentalBooking.status == "confirmed",
            RentalBooking.business_reminder_sent_at.is_(None),
            RentalBooking.start_at >= now - timedelta(minutes=1),
            RentalBooking.start_at <= now + timedelta(minutes=4),
        ).limit(100)
    )).scalars().all()
    for booking in rental_business_rows:
        booking.business_reminder_sent_at = now
        schedule_rental_business_now(str(booking.id))
        sent += 1

    if sent:
        await db.commit()
    return sent


async def appointment_reminder_loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            async with async_session() as db:
                await _send_due(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("No se pudieron enviar los recordatorios de citas")
        await asyncio.sleep(interval_seconds)
