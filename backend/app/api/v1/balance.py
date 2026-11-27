"""Pago del saldo pendiente de clientes con transferencia SPEI/CEP."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import clabe
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.balance_payment import BalancePayment
from app.models.order import Order
from app.models.receipt_validation import ReceiptValidation
from app.models.user import User
from app.schemas.order import TransferValidationRequest
from app.schemas.payment import BalanceSummaryOut
from app.services.audit_service import log_action
from app.services.balance_payment_service import (
    get_or_create_payment,
    mark_balance_paid,
    reference,
)
from app.services.cep_validation_service import CepValidationError, validate_transfer
from app.services.file_service import save_document
from app.services.order_service import get_setting_value
from app.services.receipt_validation_service import TRANSFER, create_and_validate

router = APIRouter()


def _out(payment: BalancePayment | None) -> dict | None:
    if payment is None:
        return None
    return {
        "id": str(payment.id),
        "amount": payment.amount,
        "status": payment.status,
        "reference": reference(payment),
        "transfer_tracking_key": payment.transfer_tracking_key,
        "cep_status": payment.cep_status,
        "created_at": payment.created_at,
        "paid_at": payment.paid_at,
    }


async def _receiver_accounts(db: AsyncSession) -> list[dict]:
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
        accounts.append(
            {
                "clabe": clabe_value,
                "bank_code": bank_code,
                "bank_name": (
                    await get_setting_value(db, f"BANK_NAME{suffix}", "")
                ).strip(),
                "holder": (
                    await get_setting_value(
                        db, f"BANK_ACCOUNT_HOLDER{suffix}", ""
                    )
                ).strip(),
            }
        )
    if not accounts:
        raise HTTPException(
            status_code=400,
            detail="La cuenta bancaria de la plataforma no está configurada.",
        )
    return accounts


async def _load_payment(
    db: AsyncSession, payment_id: str, user: User
) -> BalancePayment:
    payment = await db.get(BalancePayment, payment_id)
    if not payment or payment.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pago de saldo no encontrado")
    if payment.status == "approved":
        raise HTTPException(status_code=400, detail="Este saldo ya fue pagado.")
    return payment


@router.get("", response_model=BalanceSummaryOut)
async def balance_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BalancePayment)
        .where(
            BalancePayment.user_id == current_user.id,
            BalancePayment.status.in_(
                ("pending", "review", "pending_cep", "preapproved")
            ),
        )
        .order_by(BalancePayment.created_at.desc())
        .limit(1)
    )
    payment = result.scalar_one_or_none()
    return {
        "pending_balance": current_user.pending_balance or Decimal("0"),
        "payment": _out(payment),
    }


@router.post("/payments", response_model=BalanceSummaryOut)
async def create_balance_payment(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payment = await get_or_create_payment(db, current_user)
    if payment is None:
        raise HTTPException(status_code=400, detail="No tienes saldo pendiente.")
    return {
        "pending_balance": current_user.pending_balance or Decimal("0"),
        "payment": _out(payment),
    }


@router.post("/payments/{payment_id}/validate-transfer")
async def validate_balance_transfer(
    payment_id: str,
    body: TransferValidationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payment = await _load_payment(db, payment_id, current_user)

    enabled = (
        await get_setting_value(db, "CEP_ENABLED", "false")
    ).lower() == "true"
    if not enabled:
        raise HTTPException(
            status_code=400,
            detail="La validación de saldo no está activada.",
        )

    current_balance = Decimal(current_user.pending_balance or 0)
    if Decimal(payment.amount or 0) != current_balance:
        payment.status = "cancelled"
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail="Tu saldo cambió. Vuelve a generar la referencia.",
        )

    key = body.clave_rastreo.strip()
    existing_order = await db.scalar(
        select(Order.id).where(Order.transfer_tracking_key == key)
    )
    existing_balance = await db.scalar(
        select(BalancePayment.id).where(
            BalancePayment.transfer_tracking_key == key,
            BalancePayment.id != payment.id,
        )
    )
    if existing_order or existing_balance:
        raise HTTPException(
            status_code=409,
            detail="Esa transferencia ya fue usada en otro pago.",
        )

    accounts = await _receiver_accounts(db)
    sender_bank = str(body.sender_bank or "").strip()
    receiver = next(
        (
            account
            for account in accounts
            if account["bank_code"] != sender_bank
        ),
        accounts[0],
    )

    amount_cents = int(
        (Decimal(payment.amount or 0) * 100).to_integral_value()
    )
    transfer_date = body.transfer_date or date.today()
    try:
        cep = await validate_transfer(
            clave_rastreo=key,
            sender_bank=sender_bank,
            receiver_bank=receiver["bank_code"],
            receiver_account=receiver["clabe"],
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
        if exc.status in (
            "not_found",
            "pending",
            "closed",
            "amount_mismatch",
            "account_mismatch",
            "receiver_mismatch",
            "sender_mismatch",
            "key_mismatch",
            "same_bank",
        ):
            payment.cep_status = "review"
            await db.commit()
        raise HTTPException(
            status_code=status_by_error.get(exc.status, 502),
            detail=exc.message,
        ) from exc

    await mark_balance_paid(
        db,
        payment,
        tracking_key=key,
        sender_bank=sender_bank,
        receiver_bank=receiver["bank_code"],
        payload=cep,
    )
    await log_action(
        db,
        current_user.id,
        "balance.cep_validated",
        "balance_payment",
        payment.id,
        {"amount": str(payment.amount), "clave_rastreo": key},
    )
    await db.commit()
    return {
        "payment_status": "approved",
        "message": "Saldo pagado y validado por Banxico.",
        "payment": _out(payment),
    }


@router.post("/payments/{payment_id}/validate-receipt")
async def validate_balance_receipt(
    payment_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payment = await _load_payment(db, payment_id, current_user)

    enabled = (
        await get_setting_value(db, "CEP_ENABLED", "false")
    ).lower() == "true"
    validation_enabled = (
        await get_setting_value(db, "RECEIPT_VALIDATION_ENABLED", "false")
    ).lower() == "true"
    provider = (
        await get_setting_value(db, "RECEIPT_VALIDATION_PROVIDER", "gemini")
    ).strip().lower()
    api_key = (await get_setting_value(db, "APICEP_API_KEY", "")).strip()
    if not enabled or not validation_enabled or provider != "apicep" or not api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "La validación de saldo no está disponible en este momento. "
                "Intenta de 09:30 a 23:00 o paga tu saldo con tu próximo pedido."
            ),
        )

    from app.services.cep_validation_service import banxico_open

    if not banxico_open():
        raise HTTPException(
            status_code=400,
            detail=(
                "La validación de saldo está disponible de 09:30 a 23:00. "
                "Intenta dentro de ese horario o paga tu saldo con tu próximo pedido."
            ),
        )

    current_balance = Decimal(current_user.pending_balance or 0)
    if Decimal(payment.amount or 0) != current_balance:
        payment.status = "cancelled"
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail="Tu saldo cambió. Vuelve a generar la referencia.",
        )

    accounts = await _receiver_accounts(db)
    expected_recipient = " o ".join(
        f"{account['clabe']} {account.get('holder') or ''}".strip()
        for account in accounts
    )

    try:
        file_url = await save_document(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = await create_and_validate(
        db,
        "balance_payment",
        payment.id,
        file_url,
        TRANSFER,
        expected_amount=payment.amount,
        expected_date=datetime.now(timezone.utc),
        expected_recipient=expected_recipient,
    )

    if record.status == "high":
        extracted = record.extracted or {}
        details = (extracted.get("validation") or {}).get("cepDetails") or {}
        key = str(
            extracted.get("trackingKey")
            or details.get("trackingKey")
            or ""
        ).strip()
        await mark_balance_paid(
            db,
            payment,
            tracking_key=key or None,
            sender_bank=extracted.get("senderBank")
            or details.get("senderBank"),
            receiver_bank=details.get("receiverBank")
            or extracted.get("receiverBank"),
            payload=extracted,
        )
        return {
            "payment_status": "approved",
            "message": "Saldo pagado y validado por Banxico.",
            "payment": _out(payment),
        }

    payment.status = "review"
    payment.cep_status = "review"
    await db.commit()
    return {
        "payment_status": "review",
        "message": (
            "Tu comprobante quedó en revisión. "
            "El administrador lo confirmará."
        ),
        "payment": _out(payment),
    }
