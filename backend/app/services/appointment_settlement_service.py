"""Saldos, deudas por no-show y liquidaciones de citas."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.appointment_debt import AppointmentDebt
from app.models.business_ledger import BusinessLedger
from app.models.business_staff import BusinessStaff

CENT = Decimal("0.01")
NO_SHOW_FEE = Decimal("10.00")
NO_SHOW_PLATFORM = Decimal("5.00")
NO_SHOW_BUSINESS = Decimal("5.00")
MAX_UNPAID_NO_SHOWS = 3


def _q(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


async def count_pending_debts(db: AsyncSession, user_id) -> int:
    result = await db.execute(
        select(func.count(AppointmentDebt.id)).where(
            AppointmentDebt.user_id == user_id,
            AppointmentDebt.status == "pending",
        )
    )
    return int(result.scalar_one() or 0)


async def _pending_debts(db: AsyncSession, user_id) -> list[AppointmentDebt]:
    result = await db.execute(
        select(AppointmentDebt)
        .where(AppointmentDebt.user_id == user_id, AppointmentDebt.status == "pending")
        .order_by(AppointmentDebt.created_at)
        .with_for_update()
    )
    return list(result.scalars().all())


async def assign_pending_debts(db: AsyncSession, appointment: Appointment) -> Decimal:
    """Suma las deudas pendientes al efectivo a cobrar en la próxima cita."""
    debts = await _pending_debts(db, appointment.client_user_id)
    if not debts:
        return Decimal("0")
    total = _q(sum((d.amount for d in debts), Decimal("0")))
    appointment.cash_due = _q((appointment.cash_due or 0) + total)
    for debt in debts:
        debt.status = "assigned"
        debt.assigned_appointment_id = appointment.id
    return total


async def _debts_for_appointment(db: AsyncSession, appointment_id) -> list[AppointmentDebt]:
    result = await db.execute(
        select(AppointmentDebt).where(
            AppointmentDebt.assigned_appointment_id == appointment_id,
            AppointmentDebt.status == "assigned",
        )
    )
    return list(result.scalars().all())


async def release_debts(db: AsyncSession, appointment_id) -> None:
    """Devuelve a pendiente las deudas ligadas a una cita que no se completó."""
    for debt in await _debts_for_appointment(db, appointment_id):
        debt.status = "pending"
        debt.assigned_appointment_id = None


def _ledger(
    db: AsyncSession,
    appointment: Appointment,
    kind: str,
    amount,
    note: str,
    appointment_id=None,
) -> None:
    amount = _q(amount)
    if amount <= 0:
        return
    db.add(BusinessLedger(
        restaurant_id=appointment.restaurant_id,
        appointment_id=appointment_id or appointment.id,
        kind=kind,
        amount=amount,
        status="pending",
        notes=note,
    ))


async def complete_appointment(db: AsyncSession, appointment: Appointment) -> None:
    """Cierra una cita completada y registra el saldo con el negocio."""
    now = datetime.now(timezone.utc)
    for debt in await _debts_for_appointment(db, appointment.id):
        debt.status = "paid"
        debt.settled_at = now
        _ledger(
            db, appointment, "debit", debt.platform_amount,
            "Parte de la plataforma por cita no asistida cobrada en efectivo",
            appointment_id=debt.appointment_id,
        )

    if appointment.payment_mode == "cash":
        _ledger(
            db, appointment, "debit", appointment.platform_fee,
            "Comisión de cita cobrada en efectivo",
        )
    else:
        _ledger(
            db, appointment, "credit", appointment.business_credit,
            "Liquidación de cita pagada en línea",
        )


async def no_show_appointment(db: AsyncSession, appointment: Appointment) -> None:
    """Marca no-show: cobra la penalización o la deja como deuda."""
    await release_debts(db, appointment.id)
    paid_online = appointment.payment_status in ("paid", "deposit_paid")
    if paid_online:
        refund = _q((appointment.online_amount or 0) - NO_SHOW_FEE)
        appointment.refund_amount = max(refund, Decimal("0"))
        _ledger(
            db, appointment, "credit", NO_SHOW_BUSINESS,
            "Compensación por cita no asistida",
        )
        return

    db.add(AppointmentDebt(
        user_id=appointment.client_user_id,
        restaurant_id=appointment.restaurant_id,
        appointment_id=appointment.id,
        amount=NO_SHOW_FEE,
        platform_amount=NO_SHOW_PLATFORM,
        business_amount=NO_SHOW_BUSINESS,
        status="pending",
        notes="Cita no asistida",
    ))


async def cancel_appointment(db: AsyncSession, appointment: Appointment) -> None:
    await release_debts(db, appointment.id)
    if appointment.payment_mode != "cash" and appointment.payment_status in (
        "paid", "deposit_paid", "proof_review",
    ):
        appointment.refund_amount = _q(appointment.online_amount)


async def business_balance(db: AsyncSession, restaurant_id) -> dict:
    rows = (await db.execute(
        select(BusinessLedger, Appointment.staff_id)
        .outerjoin(Appointment, Appointment.id == BusinessLedger.appointment_id)
        .where(BusinessLedger.restaurant_id == restaurant_id)
        .order_by(BusinessLedger.created_at.desc())
    )).all()
    staff_rows = (await db.execute(
        select(BusinessStaff)
        .where(BusinessStaff.restaurant_id == restaurant_id)
        .order_by(BusinessStaff.sort_order, BusinessStaff.name)
    )).scalars().all()
    staff_names = {str(s.id): s.name for s in staff_rows}

    credit = sum(
        (e.amount for e, _ in rows if e.status == "pending" and e.kind == "credit"),
        Decimal("0"),
    )
    debit = sum(
        (e.amount for e, _ in rows if e.status == "pending" and e.kind == "debit"),
        Decimal("0"),
    )

    by_staff: dict[str, dict] = {
        str(s.id): {
            "staff_id": str(s.id),
            "name": s.name,
            "credit": Decimal("0"),
            "debit": Decimal("0"),
        }
        for s in staff_rows
    }
    unassigned = {
        "staff_id": None,
        "name": "Sin asignar",
        "credit": Decimal("0"),
        "debit": Decimal("0"),
    }
    for entry, staff_id in rows:
        if entry.status != "pending":
            continue
        key = str(staff_id) if staff_id else None
        bucket = by_staff.get(key) if key else unassigned
        if bucket is None:
            bucket = unassigned
        bucket[entry.kind] += entry.amount

    staff_balances = list(by_staff.values())
    if unassigned["credit"] or unassigned["debit"]:
        staff_balances.append(unassigned)
    for item in staff_balances:
        item["net"] = _q(item["credit"] - item["debit"])
        item["credit"] = _q(item["credit"])
        item["debit"] = _q(item["debit"])

    return {
        "credit": str(_q(credit)),
        "debit": str(_q(debit)),
        "net": str(_q(credit - debit)),
        "by_staff": [
            {
                "staff_id": item["staff_id"],
                "name": item["name"],
                "credit": str(item["credit"]),
                "debit": str(item["debit"]),
                "net": str(item["net"]),
            }
            for item in staff_balances
        ],
        "entries": [
            {
                "id": str(e.id),
                "appointment_id": str(e.appointment_id) if e.appointment_id else None,
                "staff_id": str(staff_id) if staff_id else None,
                "staff_name": staff_names.get(str(staff_id)) if staff_id else None,
                "kind": e.kind,
                "amount": str(e.amount),
                "status": e.status,
                "notes": e.notes,
                "settled_at": e.settled_at.isoformat() if e.settled_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e, staff_id in rows[:100]
        ],
    }


async def settle_restaurant(db: AsyncSession, restaurant_id, staff_id=None) -> dict:
    stmt = select(BusinessLedger).where(
        BusinessLedger.restaurant_id == restaurant_id,
        BusinessLedger.status == "pending",
    )
    if staff_id:
        stmt = stmt.join(
            Appointment, Appointment.id == BusinessLedger.appointment_id
        ).where(Appointment.staff_id == staff_id)
    entries = list((await db.execute(stmt)).scalars().all())
    now = datetime.now(timezone.utc)
    credit = sum((e.amount for e in entries if e.kind == "credit"), Decimal("0"))
    debit = sum((e.amount for e in entries if e.kind == "debit"), Decimal("0"))
    for entry in entries:
        entry.status = "settled"
        entry.settled_at = now
    await db.commit()
    return {
        "settled": len(entries),
        "credit": str(_q(credit)),
        "debit": str(_q(debit)),
    }
