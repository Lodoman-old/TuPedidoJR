"""Validación de comprobantes con Gemini.

La IA no aprueba pagos: extrae datos y calcula un grado de certeza para que
una persona decida. Si Gemini no está configurado, no se crea ningún registro.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

import clabe
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.receipt_validation import ReceiptValidation
from app.services import bank_service
from app.services.api_cep_service import ApiCepError, validate_receipt as validate_apicep_receipt
from app.services.cep_validation_service import BANXICO_TZ, banxico_open
from app.services.file_service import UPLOAD_DIR
from app.services.order_service import get_setting_value

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
PURCHASE = "purchase_receipt"
TRANSFER = "transfer_receipt"


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return int(max(low, min(high, round(value))))


def _normalize_text(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _normalize_kind(value) -> str:
    text = str(value or "").strip().lower()
    if any(k in text for k in ("transfer", "transferencia", "spei", "deposito", "depósito")):
        return TRANSFER
    if any(k in text for k in ("ticket", "purchase", "compra", "factura", "recibo", "receipt")):
        return PURCHASE
    return "other"


def _parse_amount(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    text = str(value).replace("$", "").replace("MXN", "").replace("mxn", "").strip()
    text = text.replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(value, time_value=None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if time_value:
        text = f"{text} {str(time_value).strip()}"
    text = text.replace("/", "-")
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt in ("%Y-%m-%d", "%d-%m-%Y"):
                parsed = parsed.replace(hour=12, minute=0)
            # Los comprobantes muestran la hora local de México.
            return parsed.replace(tzinfo=BANXICO_TZ).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def compute_confidence(
    model_confidence,
    document_type: str,
    expected_kind: str,
    amount_ok: bool | None,
    date_ok: bool | None,
    recipient_ok: bool | None,
    fields_ok: bool,
) -> tuple[int, str, list[str]]:
    """Combina la confianza del modelo con coincidencias verificables."""
    issues: list[str] = []
    try:
        model_conf = float(model_confidence or 0)
    except (TypeError, ValueError):
        model_conf = 0.0
    if 0 < model_conf <= 1:
        model_conf *= 100

    score = model_conf * 0.4
    cap = 100

    if document_type != expected_kind:
        cap = min(cap, 35)
        issues.append("El tipo de documento no coincide con el esperado.")
    else:
        score += 20

    if amount_ok is True:
        score += 20
    elif amount_ok is False:
        cap = min(cap, 45)
        issues.append("El monto no coincide con el esperado.")

    if date_ok is True:
        score += 10
    elif date_ok is False:
        cap = min(cap, 55)
        issues.append("La fecha no está dentro de la ventana esperada.")

    if recipient_ok is True:
        score += 10
    elif recipient_ok is False:
        cap = min(cap, 50)
        issues.append("El destinatario o la CLABE no coinciden.")

    if fields_ok:
        score += 10
    else:
        cap = min(cap, 60)
        issues.append("Faltan datos legibles en el comprobante.")

    final = _clamp(min(score, cap))
    if final >= 85:
        status = "high"
    elif final >= 50:
        status = "review"
    else:
        status = "low"
    return final, status, issues


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return "image/webp"


def _file_path(file_url: str) -> Path:
    name = Path(file_url or "").name
    return UPLOAD_DIR / name


def _build_prompt(
    expected_kind: str,
    expected_amount,
    expected_date,
    expected_recipient: str | None,
    context: str | None,
) -> str:
    kind_label = "ticket de compra" if expected_kind == PURCHASE else "comprobante de transferencia"
    amount_label = f"${Decimal(expected_amount):,.2f} MXN" if expected_amount is not None else "no especificado"
    if expected_date:
        if expected_date.tzinfo is None:
            expected_date = expected_date.replace(tzinfo=timezone.utc)
        date_label = expected_date.astimezone(BANXICO_TZ).strftime(
            "%Y-%m-%d %H:%M"
        )
    else:
        date_label = "no especificada"
    recipient_label = expected_recipient or "no especificado"
    context_label = context or "no especificado"
    return f"""Eres un auditor de comprobantes de TuPedidoJR. Analiza el documento adjunto.
Tipo esperado: {kind_label}.
Monto esperado: {amount_label}.
Fecha esperada (hora de México, UTC-6): {date_label}.
Destinatario/CLABE esperada: {recipient_label}.
Referencia o descripción: {context_label}.

Las fechas y horas del comprobante están en hora de México (UTC-6). No reportes
diferencias de horario por la zona horaria; solo si la fecha u hora es distinta
en esa misma zona.

Devuelve SOLO un JSON válido, sin markdown, con esta forma:
{{
  "document_type": "purchase_receipt" | "transfer_receipt" | "other",
  "is_document": true,
  "merchant": "",
  "total": 0,
  "currency": "MXN",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "reference": "",
  "recipient": "",
  "account": "",
  "confidence": 0,
  "issues": [],
  "summary": ""
}}

No inventes datos. Si no puedes leer un campo, usa null. "confidence" es tu certeza de 0 a 100
de que el documento es auténtico y coincide con los datos esperados. No apruebes ni rechaces:
solo describe lo que ves y tu nivel de certeza."""


async def _call_gemini(api_key: str, model: str, mime: str, content: bytes, prompt: str) -> dict:
    url = GEMINI_URL.format(model=model)
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(content).decode("ascii")}},
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, params={"key": api_key}, json=payload)
        for attempt in range(2):
            if response.status_code not in (429, 503) or attempt == 1:
                break
            await asyncio.sleep(1.5)
            response = await client.post(url, params={"key": api_key}, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini respondió {response.status_code}: {response.text[:300]}")
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini no devolvió candidatos")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _expected_recipient(db_bank: dict, context_recipient: str | None, context_account: str | None) -> str | None:
    pieces = [
        context_recipient,
        context_account,
        db_bank.get("holder"),
        db_bank.get("clabe"),
    ]
    text = " · ".join(str(p).strip() for p in pieces if p)
    return text or None


async def _bank_settings(db: AsyncSession) -> dict:
    return {
        "holder": (await get_setting_value(db, "BANK_ACCOUNT_HOLDER", "")).strip(),
        "clabe": (await get_setting_value(db, "BANK_CLABE", "")).strip(),
        "bank": (await get_setting_value(db, "BANK_NAME", "")).strip(),
    }


def _recipient_ok(expected: str | None, extracted: dict) -> bool | None:
    if not expected:
        return None
    actual_text = " ".join(
        str(extracted.get(key) or "")
        for key in (
            "recipient", "account", "reference", "merchant", "beneficiaryName"
        )
    )
    actual_norm = _normalize_text(actual_text)
    if not actual_norm:
        return False
    actual_digits = re.sub(r"\D", "", actual_text)

    expected_clabes = re.findall(r"\d{10,}", expected)
    for digits in expected_clabes:
        if digits in actual_digits:
            return True

    # Los comprobantes suelen mostrar la cuenta enmascarada ("**709").
    # Se compara el sufijo visible contra cada CLABE configurada.
    masked = re.findall(r"\d{3,6}", str(extracted.get("account") or ""))
    for suffix in masked:
        if any(digits.endswith(suffix) for digits in expected_clabes):
            return True

    for token in re.split(r"[^a-z0-9]+", expected.lower()):
        if len(token) >= 5 and not token.isdigit() and token in actual_norm:
            return True
    return False


BANK_ALIASES = {
    "citibanamex": "banamex",
    "banconacionaldemexico": "banamex",
    "bancoazteca": "azteca",
    "bbva": "bbvamexico",
    "bancomer": "bbvamexico",
}


def _bank_key(value) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    return BANK_ALIASES.get(key, key)


def _match_receiver_account(
    accounts: list[dict], extracted: dict
) -> dict | None:
    """Encuentra la cuenta de la plataforma que aparece en el comprobante."""
    text = " ".join(
        str(extracted.get(key) or "")
        for key in ("recipient", "account", "beneficiaryName", "reference")
    )
    digits = re.sub(r"\D", "", text)
    for account in accounts:
        clabe_value = str(account.get("clabe") or "")
        if clabe_value and clabe_value in digits:
            return account
    account_text = str(extracted.get("account") or "")
    for suffix in re.findall(r"\d{3,6}", account_text):
        matches = [
            account
            for account in accounts
            if str(account.get("clabe") or "").endswith(suffix)
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def _same_bank_still_valid(
    api_receiver_bank: str, extracted: dict, accounts: list[dict]
) -> bool:
    """Descarta un falso 'mismo banco' cuando apiCEP eligió otra cuenta.

    Con dos cuentas receptoras configuradas, apiCEP puede validar contra la
    primera y responder "misma institución" aunque el comprobante muestre la
    cuenta del otro banco. Si el comprobante apunta a una cuenta de otro banco,
    la conclusión de apiCEP no aplica.
    """
    if not api_receiver_bank or not accounts:
        return True
    destination = _match_receiver_account(accounts, extracted)
    if destination is None:
        return True
    bank_code = str(destination.get("bank_code") or "")
    destination_bank = (
        clabe.BANK_NAMES.get(bank_code) or destination.get("bank_name") or ""
    )
    if not destination_bank:
        return True
    return _bank_key(api_receiver_bank) == _bank_key(destination_bank)


def _is_same_bank_error(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "misma institución" in lowered
        or "misma institucion" in lowered
        or "same institution" in lowered
        or "banco emisor y el banco receptor" in lowered
    )


def _apicep_error_allows_fallback(text: str) -> bool:
    lowered = (text or "").lower()
    blocked = (
        "no se encontró",
        "no se encontro",
        "not found",
        "ya fue usado",
        "ya fue validado",
        "monto",
        "misma institución",
        "misma institucion",
    )
    return not any(token in lowered for token in blocked)


async def _mark_pending_cep(
    db: AsyncSession, record: ReceiptValidation, message: str
) -> ReceiptValidation:
    record.provider = "apicep"
    record.model = "apicep"
    record.status = "pending_cep"
    record.confidence = max(int(record.confidence or 0), 40)
    record.issues = [message]
    record.summary = message[:1000]
    record.error = None
    await db.commit()
    await db.refresh(record)
    return record


async def _validate_with_apicep(
    db: AsyncSession, record: ReceiptValidation
) -> ReceiptValidation:
    record.provider = "apicep"
    record.model = "apicep"
    try:
        data = await validate_apicep_receipt(
            db,
            file_url=record.file_url,
            expected_amount=record.expected_amount,
        )
    except ApiCepError as exc:
        text = (exc.message or "").strip()
        if exc.status == "closed":
            return await _mark_pending_cep(db, record, text)
        record.confidence = 0
        record.error = text[:500]
        record.issues = [text[:500]] if text else []
        if _is_same_bank_error(text):
            record.status = "review"
            api_data = (exc.payload or {}).get("extracted")
            if not isinstance(api_data, dict):
                api_data = {}
            record.extracted = {
                **(record.extracted or {}),
                "_same_bank": True,
                "_apicep_sender": api_data.get("senderBank"),
                "_apicep_receiver": api_data.get("receiverBank"),
            }
            record.summary = (
                "Transferencia entre cuentas del mismo banco. "
                "Banxico no puede validarla automáticamente; requiere revisión manual."
            )
            record.error = None
        else:
            record.status = "low"
            record.summary = text[:1000]
        await db.commit()
        await db.refresh(record)
        return record

    status = str(data.get("status") or "").lower()
    extracted = data.get("extracted") or {}
    validation = data.get("validation") or {}
    try:
        confidence = int(round(float(data.get("confidence") or 0) * 100))
    except (TypeError, ValueError):
        confidence = 0
    if confidence <= 0:
        confidence = 100 if status == "valid" else 0

    amount_ok = None
    amount = extracted.get("amount")
    if record.expected_amount is not None and amount is not None:
        try:
            tolerance = Decimal(
                await get_setting_value(db, "RECEIPT_AMOUNT_TOLERANCE", "10.0")
            )
        except (InvalidOperation, ValueError):
            tolerance = Decimal("10.0")
        amount_ok = (
            abs(Decimal(str(amount)) - Decimal(record.expected_amount)) <= tolerance
        )

    confirmed = bool(validation.get("banxicoConfirmed"))
    cep_status = str(validation.get("cepStatus") or "").upper().replace(" ", "_")
    reused = validation.get("cepPreviouslyValidated") is True
    error_text = str(data.get("error") or "")

    if _is_same_bank_error(error_text):
        record.confidence = min(confidence, 40)
        record.status = "review"
        record.document_type = TRANSFER
        record.extracted = {
            **extracted,
            "validation": validation,
            "_same_bank": True,
        }
        record.issues = [
            "Transferencia entre cuentas del mismo banco. "
            "Banxico no puede validarla automáticamente; requiere revisión manual."
        ]
        record.summary = (
            "Mismo banco: no hay CEP de Banxico. Revisa el comprobante manualmente."
        )
        record.error = None
        await db.commit()
        await db.refresh(record)
        return record

    issues: list[str] = []
    if status != "valid" or not confirmed or cep_status != "LIQUIDADO":
        issues.append(
            error_text or "apiCEP no confirmó la transferencia con Banxico."
        )
    if amount_ok is False:
        issues.append("El monto no coincide con el esperado.")
    if reused:
        issues.append("Ese comprobante ya fue validado antes.")

    valid = (
        status == "valid"
        and confirmed
        and cep_status == "LIQUIDADO"
        and amount_ok is not False
        and not reused
    )
    pending_cep = status == "pending" or cep_status == "EN_PROCESO"
    record.document_type = TRANSFER
    record.confidence = 100 if valid else min(confidence, 40)
    if pending_cep:
        record.status = "pending_cep"
    elif valid:
        record.status = "high"
    elif status == "valid":
        record.status = "review"
    else:
        record.status = "low"
    record.extracted = {
        **extracted,
        "validation": validation,
        "downloads": data.get("downloads") or {},
        "validation_id": data.get("validationId"),
    }
    record.issues = issues
    record.summary = (
        "Transferencia validada por Banxico."
        if valid
        else (
            "Banxico todavía no genera el CEP. Se reintentará automáticamente."
            if pending_cep
            else (error_text or "No se pudo confirmar la transferencia.")
        )
    )[:1000]
    record.error = None if valid else (error_text or None)
    await db.commit()
    await db.refresh(record)
    return record


async def _validate_with_gemini(db: AsyncSession, record: ReceiptValidation) -> ReceiptValidation:
    api_key = (await get_setting_value(db, "GEMINI_API_KEY", "")).strip()
    model = (await get_setting_value(db, "GEMINI_MODEL", "gemini-3.5-flash-lite")).strip()
    record.provider = "gemini"
    record.model = model
    if not api_key:
        record.status = "review"
        record.error = "Falta configurar la API key de Gemini."
        record.summary = "El respaldo con Gemini no está configurado."
        record.issues = ["Falta configurar la API key de Gemini."]
        await db.commit()
        await db.refresh(record)
        return record

    path = _file_path(record.file_url)
    if not path.exists():
        record.confidence = 0
        record.status = "low"
        record.error = "No se encontró el archivo del comprobante."
        await db.commit()
        await db.refresh(record)
        return record

    try:
        tolerance = Decimal(await get_setting_value(db, "RECEIPT_AMOUNT_TOLERANCE", "10.0"))
    except (InvalidOperation, ValueError):
        tolerance = Decimal("10.0")
    try:
        window_hours = int(await get_setting_value(db, "RECEIPT_DATE_WINDOW_HOURS", "48"))
    except (TypeError, ValueError):
        window_hours = 48

    bank = await _bank_settings(db)
    if record.expected_kind == TRANSFER:
        expected_recipient = record.expected_recipient or _expected_recipient(bank, None, None)
    else:
        # En un ticket de compra el comercio puede ser cualquiera; no se compara
        # contra la cuenta bancaria de la plataforma.
        expected_recipient = record.expected_recipient
    prompt = _build_prompt(
        record.expected_kind,
        record.expected_amount,
        record.expected_date,
        expected_recipient,
        None,
    )

    try:
        content = path.read_bytes()
        extracted = await _call_gemini(api_key, model, _mime_for(path), content, prompt)
    except Exception as exc:
        logger.exception("No se pudo validar el comprobante %s", record.id)
        record.confidence = 0
        record.status = "low"
        record.error = str(exc)[:500]
        record.issues = [record.error]
        await db.commit()
        await db.refresh(record)
        return record

    document_type = _normalize_kind(extracted.get("document_type"))
    total = _parse_amount(extracted.get("total"))
    parsed_date = _parse_datetime(extracted.get("date"), extracted.get("time"))

    amount_ok = None
    if record.expected_amount is not None:
        if total is None:
            amount_ok = False
        else:
            amount_ok = abs(total - Decimal(record.expected_amount)) <= tolerance

    date_ok = None
    if record.expected_date is not None:
        if parsed_date is None:
            date_ok = False
        else:
            expected = record.expected_date
            if expected.tzinfo is None:
                expected = expected.replace(tzinfo=timezone.utc)
            date_ok = abs((parsed_date - expected).total_seconds()) <= window_hours * 3600

    recipient_ok = (
        _recipient_ok(expected_recipient, extracted)
        if record.expected_kind == TRANSFER else None
    )
    fields_ok = bool(total is not None and (parsed_date is not None or extracted.get("reference")))

    model_confidence = extracted.get("confidence")
    confidence, status, issues = compute_confidence(
        model_confidence, document_type, record.expected_kind,
        amount_ok, date_ok, recipient_ok, fields_ok,
    )
    model_issues = extracted.get("issues")
    if isinstance(model_issues, list):
        issues.extend(str(item) for item in model_issues if item)

    record.document_type = document_type
    record.confidence = confidence
    record.status = status
    extracted["_checks"] = {
        "amount_ok": amount_ok,
        "date_ok": date_ok,
        "recipient_ok": recipient_ok,
        "fields_ok": fields_ok,
    }
    record.extracted = extracted
    record.issues = issues
    record.summary = (extracted.get("summary") or "")[:1000] or None
    record.error = None
    await db.commit()
    await db.refresh(record)
    return record


async def _fallback_with_gemini(
    db: AsyncSession,
    record: ReceiptValidation,
    reason: str,
    *,
    same_bank: bool = False,
) -> ReceiptValidation:
    fallback_enabled = (
        await get_setting_value(db, "RECEIPT_GEMINI_FALLBACK_ENABLED", "true")
    ).lower() == "true"
    gemini_key = (await get_setting_value(db, "GEMINI_API_KEY", "")).strip()

    if not fallback_enabled:
        if same_bank:
            message = (
                "Transferencia entre cuentas del mismo banco y sin respaldo de Gemini. "
                "Requiere revisión manual."
            )
            record.provider = "apicep"
            record.status = "review"
            record.issues = [message] + (record.issues or [])
            record.summary = message
            record.error = None
            record.extracted = {
                **(record.extracted or {}),
                "_same_bank": True,
                "_fallback_reason": reason,
            }
            await db.commit()
            await db.refresh(record)
            return record
        return await _mark_pending_cep(
            db,
            record,
            "Banxico valida de 09:30 a 23:00. "
            "Tu comprobante quedó pendiente para intentar al abrir.",
        )

    if not gemini_key:
        if same_bank:
            message = (
                "Transferencia entre cuentas del mismo banco y sin respaldo de Gemini. "
                "Requiere revisión manual."
            )
            record.provider = "apicep"
            record.status = "review"
            record.issues = [message] + (record.issues or [])
            record.summary = message
            record.error = None
            record.extracted = {
                **(record.extracted or {}),
                "_same_bank": True,
                "_fallback_reason": reason,
            }
            await db.commit()
            await db.refresh(record)
            return record
        return await _mark_pending_cep(
            db,
            record,
            "Banxico valida de 09:30 a 23:00. "
            "Tu comprobante quedó pendiente para reintentar al abrir.",
        )

    api_receiver_bank = str(
        (record.extracted or {}).get("_apicep_receiver") or ""
    )
    gemini = await _validate_with_gemini(db, record)
    gemini_error = gemini.error
    checks = (gemini.extracted or {}).get("_checks") or {}

    if same_bank:
        try:
            accounts = await bank_service.receiver_accounts(db)
        except ValueError:
            accounts = []
        if not _same_bank_still_valid(
            api_receiver_bank, gemini.extracted or {}, accounts
        ):
            same_bank = False

    if record.entity_type != "order_transfer":
        gemini.extracted = {
            **(gemini.extracted or {}),
            "_same_bank": same_bank,
            "_fallback_reason": reason,
        }
        gemini.status = "review"
        if same_bank:
            gemini.summary = (
                "Mismo banco: Banxico no emite CEP. Revisión manual."
            )
        elif reason == "Transferencia entre cuentas del mismo banco.":
            gemini.summary = (
                "No pudimos validar la transferencia automáticamente. "
                "El administrador la revisará."
            )
        else:
            gemini.summary = (
                reason or "El administrador revisará tu comprobante."
            )
        if gemini_error and gemini_error not in (gemini.issues or []):
            gemini.issues = [*(gemini.issues or []), gemini_error]
        gemini.error = gemini_error
        await db.commit()
        await db.refresh(gemini)
        return gemini

    try:
        min_conf = int(
            await get_setting_value(db, "RECEIPT_GEMINI_MIN_CONFIDENCE", "95")
        )
    except (TypeError, ValueError):
        min_conf = 95
    try:
        cap_key = (
            "RECEIPT_SAME_BANK_MAX_AMOUNT"
            if same_bank
            else "RECEIPT_AUTO_APPROVE_MAX_AMOUNT"
        )
        cap = Decimal(
            await get_setting_value(db, cap_key, "200.0")
        )
    except (InvalidOperation, ValueError):
        cap = Decimal("200.0")

    expected_value = None
    if record.expected_amount is not None:
        try:
            expected_value = Decimal(str(record.expected_amount))
        except (InvalidOperation, ValueError):
            expected_value = None
    total = _parse_amount((gemini.extracted or {}).get("total"))
    exact_amount = (
        total is not None
        and expected_value is not None
        and total == expected_value
    )

    exact = (
        gemini.document_type == TRANSFER
        and expected_value is not None
        and expected_value <= cap
        and gemini.confidence >= min_conf
        and exact_amount
        and checks.get("recipient_ok") is True
        and checks.get("date_ok") in (True, None)
        and checks.get("fields_ok") is True
        and not gemini.issues
    )

    extracted = dict(gemini.extracted or {})
    extracted["_same_bank"] = same_bank
    extracted["_fallback_reason"] = reason

    if exact:
        extracted["_preapproved"] = True
        gemini.extracted = extracted
        gemini.status = "preapproved"
        gemini.issues = []
        gemini.summary = (
            "Pago preaprobado con Gemini. Se confirmará con Banxico al abrir."
            if not same_bank
            else "Pago preaprobado con Gemini (mismo banco). Verifica el ingreso en tu cuenta."
        )
        gemini.error = None
        await db.commit()
        await db.refresh(gemini)
        return gemini

    issues = list(gemini.issues or [])
    if expected_value is not None and expected_value > cap:
        issues.append(
            f"El monto supera el límite de autoaprobación (${cap:,.2f})."
        )
    if gemini.confidence < min_conf:
        issues.append(
            f"La confianza de Gemini ({gemini.confidence}%) es menor al mínimo ({min_conf}%)."
        )
    if not exact_amount:
        issues.append("No se pudo confirmar que el monto coincida exactamente.")
    if checks.get("recipient_ok") is not True:
        issues.append("No se pudo confirmar la CLABE destino.")
    if same_bank:
        issues.append(
            "Mismo banco: Banxico no emite CEP; requiere revisión manual."
        )
    if gemini_error and gemini_error not in issues:
        issues.append(gemini_error)
    gemini.extracted = extracted
    gemini.status = "review"
    gemini.issues = issues
    gemini.summary = (
        "Pago en revisión. El administrador debe confirmar la transferencia."
    )
    gemini.error = gemini_error
    await db.commit()
    await db.refresh(gemini)
    return gemini


async def _validate_record(
    db: AsyncSession, record: ReceiptValidation
) -> ReceiptValidation:
    enabled = (
        await get_setting_value(db, "RECEIPT_VALIDATION_ENABLED", "false")
    ).lower() == "true"
    if not enabled:
        return record

    provider = (
        await get_setting_value(db, "RECEIPT_VALIDATION_PROVIDER", "gemini")
    ).strip().lower()
    if provider != "apicep" or record.expected_kind != TRANSFER:
        return await _validate_with_gemini(db, record)

    force_closed = (
        await get_setting_value(db, "CEP_FORCE_CLOSED", "false")
    ).lower() == "true"
    if force_closed or not banxico_open():
        return await _fallback_with_gemini(
            db,
            record,
            "Banxico está fuera de horario (09:30 a 23:00).",
        )
    apicep_key = (await get_setting_value(db, "APICEP_API_KEY", "")).strip()
    if not apicep_key:
        return await _fallback_with_gemini(
            db,
            record,
            "apiCEP no está configurado.",
        )

    result = await _validate_with_apicep(db, record)
    if result.status == "high":
        return result
    if result.status == "pending_cep":
        return await _fallback_with_gemini(
            db,
            result,
            "Banxico todavía no tiene el CEP disponible.",
        )
    if (result.extracted or {}).get("_same_bank"):
        return await _fallback_with_gemini(
            db,
            result,
            "Transferencia entre cuentas del mismo banco.",
            same_bank=True,
        )
    if result.status == "low":
        reason = result.error or result.summary or ""
        if _apicep_error_allows_fallback(reason):
            return await _fallback_with_gemini(db, result, reason)
    return result


async def _run_validation(
    entity_type: str,
    entity_id: str,
    file_url: str,
    expected_kind: str,
    expected_amount,
    expected_date,
    expected_recipient: str | None,
) -> None:
    async with async_session() as db:
        enabled = (await get_setting_value(db, "RECEIPT_VALIDATION_ENABLED", "false")).lower() == "true"
        if not enabled:
            return
        provider = (
            await get_setting_value(db, "RECEIPT_VALIDATION_PROVIDER", "gemini")
        ).strip().lower()
        if provider == "apicep" and expected_kind == TRANSFER:
            configured = bool(
                (await get_setting_value(db, "APICEP_API_KEY", "")).strip()
            )
        else:
            configured = bool(
                (await get_setting_value(db, "GEMINI_API_KEY", "")).strip()
            )
        if not configured:
            return
        record = ReceiptValidation(
            entity_type=entity_type,
            entity_id=UUID(str(entity_id)),
            file_url=file_url,
            expected_kind=expected_kind,
            expected_amount=expected_amount,
            expected_date=expected_date,
            expected_recipient=expected_recipient,
            status="review",
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        await _validate_record(db, record)


async def create_and_validate(
    db: AsyncSession,
    entity_type: str,
    entity_id,
    file_url: str,
    expected_kind: str,
    expected_amount=None,
    expected_date=None,
    expected_recipient: str | None = None,
    plan_months: int | None = None,
) -> ReceiptValidation | None:
    """Crea el registro de validación y lo evalúa en la sesión del llamador.

    Siempre deja el registro para revisión manual; si la IA está activa y hay
    clave, además lo evalúa y actualiza el grado de certeza.
    """
    record = ReceiptValidation(
        entity_type=entity_type,
        entity_id=UUID(str(entity_id)),
        file_url=file_url,
        expected_kind=expected_kind,
        expected_amount=expected_amount,
        expected_date=expected_date,
        expected_recipient=expected_recipient,
        plan_months=plan_months,
        status="review",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    enabled = (await get_setting_value(db, "RECEIPT_VALIDATION_ENABLED", "false")).lower() == "true"
    if not enabled:
        return record
    return await _validate_record(db, record)


def schedule_receipt_validation(
    entity_type: str,
    entity_id: str,
    file_url: str,
    expected_kind: str,
    expected_amount=None,
    expected_date=None,
    expected_recipient: str | None = None,
) -> None:
    try:
        asyncio.create_task(_run_validation(
            entity_type, entity_id, file_url, expected_kind,
            expected_amount, expected_date, expected_recipient,
        ))
    except RuntimeError:
        logger.debug("No event loop for receipt validation")


async def revalidate_receipt(db: AsyncSession, record: ReceiptValidation) -> ReceiptValidation:
    return await _validate_record(db, record)
