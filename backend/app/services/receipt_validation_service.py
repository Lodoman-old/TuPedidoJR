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

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.receipt_validation import ReceiptValidation
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
            return parsed.replace(tzinfo=timezone.utc)
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
    date_label = expected_date.strftime("%Y-%m-%d %H:%M") if expected_date else "no especificada"
    recipient_label = expected_recipient or "no especificado"
    context_label = context or "no especificado"
    return f"""Eres un auditor de comprobantes de TuPedidoJR. Analiza el documento adjunto.
Tipo esperado: {kind_label}.
Monto esperado: {amount_label}.
Fecha esperada: {date_label}.
Destinatario/CLABE esperada: {recipient_label}.
Referencia o descripción: {context_label}.

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
    expected_norm = _normalize_text(expected)
    actual_parts = [
        extracted.get("recipient"), extracted.get("account"),
        extracted.get("reference"), extracted.get("merchant"),
    ]
    actual_norm = _normalize_text(" ".join(str(p) for p in actual_parts if p))
    if not actual_norm:
        return False
    expected_digits = re.sub(r"\D", "", expected)
    if len(expected_digits) >= 10:
        if expected_digits in re.sub(r"\D", "", actual_norm):
            return True
    for token in re.split(r"[^a-z0-9]+", expected.lower()):
        if len(token) >= 5 and token in actual_norm:
            return True
    return False


async def _validate_record(db: AsyncSession, record: ReceiptValidation) -> ReceiptValidation:
    enabled = (await get_setting_value(db, "RECEIPT_VALIDATION_ENABLED", "false")).lower() == "true"
    api_key = (await get_setting_value(db, "GEMINI_API_KEY", "")).strip()
    model = (await get_setting_value(db, "GEMINI_MODEL", "gemini-2.5-flash")).strip()
    if not enabled or not api_key:
        return record

    record.provider = "gemini"
    record.model = model
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
    record.extracted = extracted
    record.issues = issues
    record.summary = (extracted.get("summary") or "")[:1000] or None
    record.error = None
    await db.commit()
    await db.refresh(record)
    return record


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
        api_key = (await get_setting_value(db, "GEMINI_API_KEY", "")).strip()
        if not enabled or not api_key:
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
