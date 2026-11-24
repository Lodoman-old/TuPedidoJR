"""Validación de transferencias SPEI contra el CEP de Banxico."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import clabe
from cep import Transferencia
from cep.exc import CepNotAvailableError, MaxRequestError, TransferNotFoundError

logger = logging.getLogger(__name__)

BANXICO_TZ = ZoneInfo("America/Mexico_City")


class CepValidationError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def banxico_open() -> bool:
    now = datetime.now(BANXICO_TZ)
    if now.hour < 9 or now.hour >= 23:
        return False
    if now.hour == 9 and now.minute < 30:
        return False
    return True


async def validate_transfer(
    *,
    clave_rastreo: str,
    sender_bank: str,
    receiver_bank: str,
    receiver_account: str,
    amount_cents: int,
    transfer_date: date,
) -> dict:
    sender_bank = str(sender_bank or "").strip()
    receiver_bank = str(receiver_bank or "").strip()
    receiver_account = _digits(receiver_account)
    clave_rastreo = str(clave_rastreo or "").strip()

    if sender_bank not in clabe.BANK_NAMES:
        raise CepValidationError(
            "invalid_bank", "El banco emisor seleccionado no es válido."
        )
    if receiver_bank not in clabe.BANK_NAMES:
        raise CepValidationError(
            "invalid_bank", "El banco receptor no es válido."
        )
    if len(receiver_account) != 18:
        raise CepValidationError(
            "invalid_account", "La CLABE receptora no está configurada correctamente."
        )
    if not clave_rastreo:
        raise CepValidationError(
            "missing_key", "Escribe la clave de rastreo de tu transferencia."
        )
    if amount_cents <= 0:
        raise CepValidationError("invalid_amount", "El monto del pedido no es válido.")
    if sender_bank == receiver_bank:
        raise CepValidationError(
            "same_bank",
            "Tu transferencia es entre cuentas del mismo banco. Banxico no puede "
            "validarla; sube tu comprobante para revisión manual.",
        )
    if transfer_date > date.today():
        raise CepValidationError(
            "invalid_date", "La fecha de la transferencia no puede ser futura."
        )
    if not banxico_open():
        raise CepValidationError(
            "closed",
            "Banxico valida transferencias de 09:30 a 23:00. Sube tu comprobante "
            "para preaprobarlo con Gemini o intenta dentro de ese horario.",
        )

    def _run():
        return Transferencia.validar(
            fecha=transfer_date,
            clave_rastreo=clave_rastreo,
            emisor=sender_bank,
            receptor=receiver_bank,
            cuenta=receiver_account,
            monto=amount_cents,
        )

    try:
        transfer = await asyncio.to_thread(_run)
    except TransferNotFoundError as exc:
        raise CepValidationError(
            "not_found",
            "No se encontró la transferencia. Revisa la clave de rastreo, "
            "el banco emisor y la fecha.",
        ) from exc
    except CepNotAvailableError as exc:
        raise CepValidationError(
            "pending",
            "La transferencia existe, pero Banxico todavía no genera el CEP. "
            "Intenta de nuevo en unos minutos.",
        ) from exc
    except MaxRequestError as exc:
        raise CepValidationError(
            "rate_limited",
            "Banxico está limitando las consultas. Intenta de nuevo más tarde.",
        ) from exc
    except Exception as exc:
        logger.exception("Error validando CEP con Banxico")
        raise CepValidationError(
            "error", "No se pudo validar con Banxico. Intenta más tarde."
        ) from exc

    if int(transfer.monto or 0) != int(amount_cents):
        raise CepValidationError(
            "amount_mismatch",
            "El monto de la transferencia no coincide con el total del pedido.",
        )
    if _digits(getattr(transfer.beneficiario, "numero", "")) != receiver_account:
        raise CepValidationError(
            "account_mismatch",
            "La transferencia no llegó a la cuenta configurada.",
        )
    if str(transfer.receptor) != receiver_bank:
        raise CepValidationError(
            "receiver_mismatch",
            "El banco receptor de la transferencia no coincide.",
        )
    if str(transfer.emisor) != sender_bank:
        raise CepValidationError(
            "sender_mismatch",
            "El banco emisor de la transferencia no coincide.",
        )
    if str(transfer.clave_rastreo) != clave_rastreo:
        raise CepValidationError(
            "key_mismatch",
            "La clave de rastreo no coincide con la transferencia.",
        )

    return {
        "status": "valid",
        "clave_rastreo": str(transfer.clave_rastreo),
        "monto": str(transfer.monto_pesos),
        "monto_centavos": int(transfer.monto or 0),
        "fecha_operacion": (
            transfer.fecha_operacion.isoformat()
            if transfer.fecha_operacion
            else None
        ),
        "fecha_abono": (
            transfer.fecha_abono.isoformat() if transfer.fecha_abono else None
        ),
        "emisor": str(transfer.emisor),
        "receptor": str(transfer.receptor),
        "beneficiario": _digits(getattr(transfer.beneficiario, "numero", "")),
        "concepto": transfer.concepto,
        "tipo_pago": int(transfer.tipo_pago or 0),
    }
