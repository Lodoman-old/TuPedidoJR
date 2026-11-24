"""Lógica de pagos del saldo pendiente de clientes."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.balance_payment import BalancePayment
from app.models.receipt_validation import ReceiptValidation
from app.models.user import User
from app.services.rounding import round_half_down

OPEN_STATUSES = ("pending", "review", "pending_cep", "preapproved")


def reference(payment: BalancePayment) -> str:
    return str(payment.id)[:8].upper()


async def get_or_create_payment(
    db: AsyncSession, user: User
) -> BalancePayment | None:
    amount = round_half_down(Decimal(user.pending_balance or 0))
    if amount <= 0:
        return None

    result = await db.execute(
        select(BalancePayment)
        .where(
            BalancePayment.user_id == user.id,
            BalancePayment.status.in_(OPEN_STATUSES),
        )
        .order_by(BalancePayment.created_at.desc())
        .limit(1)
    )
    payment = result.scalar_one_or_none()
    if payment:
        if payment.status == "pending" and not payment.transfer_tracking_key:
            payment.amount = amount
            await db.commit()
            await db.refresh(payment)
        return payment

    payment = BalancePayment(
        user_id=user.id,
        amount=amount,
        status="pending",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


async def mark_balance_paid(
    db: AsyncSession,
    payment: BalancePayment,
    *,
    tracking_key: str | None = None,
    sender_bank: str | None = None,
    receiver_bank: str | None = None,
    payload: dict | None = None,
) -> BalancePayment:
    user = await db.get(User, payment.user_id)
    if user:
        remaining = round_half_down(
            Decimal(user.pending_balance or 0)
            - Decimal(payment.amount or 0)
        )
        user.pending_balance = max(remaining, Decimal("0"))

    payment.status = "approved"
    payment.paid_at = datetime.now(timezone.utc)
    payment.cep_status = "valid"
    payment.cep_validated_at = datetime.now(timezone.utc)
    if tracking_key:
        payment.transfer_tracking_key = tracking_key
    if sender_bank:
        payment.cep_sender_bank = sender_bank
    if receiver_bank:
        payment.cep_receiver_bank = receiver_bank
    if payload is not None:
        payment.cep_payload = payload
    await db.commit()
    await db.refresh(payment)
    return payment


async def settle_balance_payment_record(
    db: AsyncSession,
    record: ReceiptValidation,
    approved: bool,
) -> None:
    payment = await db.get(BalancePayment, record.entity_id)
    if not payment:
        return

    if not approved:
        payment.status = "rejected"
        record.status = "rejected"
        await db.commit()
        return

    if payment.status == "approved":
        record.status = "approved"
        await db.commit()
        return

    extracted = record.extracted or {}
    details = (extracted.get("validation") or {}).get("cepDetails") or {}
    key = str(
        extracted.get("trackingKey") or details.get("trackingKey") or ""
    ).strip()
    sender = extracted.get("senderBank") or details.get("senderBank")
    receiver = details.get("receiverBank") or extracted.get("receiverBank")
    await mark_balance_paid(
        db,
        payment,
        tracking_key=key or None,
        sender_bank=sender,
        receiver_bank=receiver,
        payload=extracted,
    )
    record.status = "approved"
    await db.commit()
