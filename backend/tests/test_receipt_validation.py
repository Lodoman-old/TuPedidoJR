import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

import app.services.receipt_validation_service as svc
from app.models.receipt_validation import ReceiptValidation
from app.services.file_service import UPLOAD_DIR
from app.services.receipt_validation_service import (
    PURCHASE,
    TRANSFER,
    compute_confidence,
)


def test_high_confidence_when_everything_matches():
    score, status, issues = compute_confidence(
        95, PURCHASE, PURCHASE, True, True, True, True
    )
    assert score >= 85
    assert status == "high"
    assert issues == []


def test_amount_mismatch_caps_confidence():
    score, status, issues = compute_confidence(
        95, PURCHASE, PURCHASE, False, True, True, True
    )
    assert score <= 45
    assert status == "low"
    assert any("monto" in issue.lower() for issue in issues)


def test_date_mismatch_sends_to_review():
    score, status, issues = compute_confidence(
        95, TRANSFER, TRANSFER, True, False, True, True
    )
    assert score <= 55
    assert status == "review"
    assert any("fecha" in issue.lower() for issue in issues)


def test_wrong_document_type_caps_low():
    score, status, issues = compute_confidence(
        95, TRANSFER, PURCHASE, True, True, True, True
    )
    assert score <= 35
    assert status == "low"
    assert any("tipo de documento" in issue.lower() for issue in issues)


def test_missing_fields_caps_review():
    score, status, issues = compute_confidence(
        95, PURCHASE, PURCHASE, True, True, None, False
    )
    assert score <= 60
    assert status == "review"
    assert any("datos legibles" in issue.lower() for issue in issues)


def test_model_confidence_between_zero_and_one_is_normalized():
    score, status, _ = compute_confidence(
        0.95, PURCHASE, PURCHASE, True, True, True, True
    )
    assert score >= 85
    assert status == "high"


async def _fake_settings(db, key: str, default: str) -> str:
    values = {
        "RECEIPT_VALIDATION_ENABLED": "true",
        "GEMINI_API_KEY": "test-key",
        "GEMINI_MODEL": "gemini-2.5-flash",
        "RECEIPT_AMOUNT_TOLERANCE": "10",
        "RECEIPT_DATE_WINDOW_HOURS": "48",
        "BANK_ACCOUNT_HOLDER": "TuPedidoJR",
        "BANK_CLABE": "012345678901234567",
    }
    return values.get(key, default)


async def _run_record(db_session, monkeypatch, total):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / "test_receipt_validation.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    monkeypatch.setattr(svc, "get_setting_value", _fake_settings)

    async def fake_call(*args, **kwargs):
        return {
            "document_type": "purchase_receipt",
            "total": total,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "time": "14:00",
            "merchant": "Pizzas Memo",
            "reference": "123",
            "confidence": 95,
            "issues": [],
            "summary": "Ticket legible.",
        }

    monkeypatch.setattr(svc, "_call_gemini", fake_call)
    record = ReceiptValidation(
        entity_type="mandado_purchase",
        entity_id=uuid.uuid4(),
        file_url="/static/uploads/test_receipt_validation.pdf",
        expected_kind="purchase_receipt",
        expected_amount=Decimal("150.00"),
        expected_date=datetime.now(timezone.utc),
        status="review",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    try:
        return await svc._validate_record(db_session, record)
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_validate_record_high(db_session, monkeypatch):
    updated = await _run_record(db_session, monkeypatch, 150)
    assert updated.confidence >= 85
    assert updated.status == "high"
    assert updated.extracted["total"] == 150
    assert updated.document_type == "purchase_receipt"


@pytest.mark.asyncio
async def test_validate_record_amount_mismatch_is_low(db_session, monkeypatch):
    updated = await _run_record(db_session, monkeypatch, 200)
    assert updated.confidence <= 45
    assert updated.status == "low"
    assert any("monto" in issue.lower() for issue in updated.issues)
