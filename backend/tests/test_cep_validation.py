"""Validación de transferencias SPEI con el CEP de Banxico."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.v1 import orders as orders_module
from app.api.v1 import payments as payments_module
from app.core.security import decode_access_token
from app.models.order import Order
from app.models.receipt_validation import ReceiptValidation
from app.models.restaurant import Restaurant
from app.models.setting import Setting
from app.models.user import User
from app.services import order_transfer_service as ots
from app.services import receipt_validation_service as rvs
from app.services import api_cep_service
from app.services.api_cep_service import ApiCepError
from app.services.cep_validation_service import CepValidationError, validate_transfer


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Cliente CEP",
            "email": email,
            "phone": "4121234567",
            "password": "pass123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _settings(db_session, enabled: bool = True) -> None:
    db_session.add_all([
        Setting(key="CEP_ENABLED", value="true" if enabled else "false"),
        Setting(key="BANK_CLABE", value="012180004643051249"),
    ])
    await db_session.commit()


async def _apicep_settings(db_session) -> None:
    await _settings(db_session)
    db_session.add_all([
        Setting(key="RECEIPT_VALIDATION_ENABLED", value="true"),
        Setting(key="RECEIPT_VALIDATION_PROVIDER", value="apicep"),
        Setting(key="APICEP_API_KEY", value="apicep_test_key"),
        Setting(key="APP_PUBLIC_URL", value="https://tupedidojr.com"),
    ])
    await db_session.commit()


async def _order(db_session, token: str, total: str = "100.00") -> Order:
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Negocio CEP",
        slug=f"cep-{uuid.uuid4().hex[:6]}",
        owner_id=user_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 1",
        is_open=True,
        status="active",
        delivery_enabled=True,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    await db_session.flush()
    order = Order(
        id=uuid.uuid4(),
        user_id=user_id,
        restaurant_id=resto.id,
        status="pending",
        subtotal=Decimal(total),
        delivery_fee=Decimal("0"),
        total=Decimal(total),
        delivery_address="Calle 1",
        delivery_location="SRID=4326;POINT(-100.99 20.64)",
        payment_method="transfer",
        payment_status="pending",
        placed_at=datetime.now(timezone.utc),
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


def _fake_validate(calls):
    async def fake(**kwargs):
        calls.append(kwargs)
        return {
            "status": "valid",
            "clave_rastreo": kwargs["clave_rastreo"],
            "monto": "100.00",
            "monto_centavos": kwargs["amount_cents"],
            "emisor": kwargs["sender_bank"],
            "receptor": kwargs["receiver_bank"],
            "beneficiario": kwargs["receiver_account"],
        }

    return fake


async def test_cep_validates_and_approves(client, db_session, monkeypatch):
    token = await _register(client, "cep1@test.com")
    await _settings(db_session)
    order = await _order(db_session, token)
    calls = []
    monkeypatch.setattr(orders_module, "validate_transfer", _fake_validate(calls))

    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer",
        headers=_headers(token),
        json={
            "clave_rastreo": "ABC12345",
            "sender_bank": "40014",
            "transfer_date": str(date.today()),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "approved"
    assert resp.json()["cep_status"] == "valid"

    await db_session.refresh(order)
    assert order.payment_status == "approved"
    assert order.cep_status == "valid"
    assert order.transfer_tracking_key == "ABC12345"
    assert order.cep_sender_bank == "40014"
    assert order.cep_receiver_bank == "40012"
    assert order.cep_payload["monto_centavos"] == 10000
    assert calls and calls[0]["receiver_account"] == "012180004643051249"


async def test_cep_duplicate_key_rejected(client, db_session, monkeypatch):
    token = await _register(client, "cep2@test.com")
    await _settings(db_session)
    first = await _order(db_session, token)
    calls = []
    monkeypatch.setattr(orders_module, "validate_transfer", _fake_validate(calls))

    payload = {
        "clave_rastreo": "DUP12345",
        "sender_bank": "40014",
        "transfer_date": str(date.today()),
    }
    ok = await client.post(
        f"/api/v1/orders/{first.id}/validate-transfer",
        headers=_headers(token),
        json=payload,
    )
    assert ok.status_code == 200, ok.text

    second = await _order(db_session, token)
    dup = await client.post(
        f"/api/v1/orders/{second.id}/validate-transfer",
        headers=_headers(token),
        json=payload,
    )
    assert dup.status_code == 409


async def test_cep_not_found(client, db_session, monkeypatch):
    token = await _register(client, "cep3@test.com")
    await _settings(db_session)
    order = await _order(db_session, token)

    async def not_found(**kwargs):
        raise CepValidationError("not_found", "No se encontró la transferencia.")

    monkeypatch.setattr(orders_module, "validate_transfer", not_found)
    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer",
        headers=_headers(token),
        json={"clave_rastreo": "NOPE1234", "sender_bank": "40014"},
    )
    assert resp.status_code == 404


async def test_cep_disabled(client, db_session):
    token = await _register(client, "cep4@test.com")
    await _settings(db_session, enabled=False)
    order = await _order(db_session, token)
    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer",
        headers=_headers(token),
        json={"clave_rastreo": "ABC12345", "sender_bank": "40014"},
    )
    assert resp.status_code == 400


async def test_cep_forbidden_for_other_user(client, db_session):
    owner = await _register(client, "cep5@test.com")
    other = await _register(client, "cep6@test.com")
    await _settings(db_session)
    order = await _order(db_session, owner)
    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer",
        headers=_headers(other),
        json={"clave_rastreo": "ABC12345", "sender_bank": "40014"},
    )
    assert resp.status_code == 404


async def test_transfer_banks_list(client):
    resp = await client.get("/api/v1/payments/transfer-banks")
    assert resp.status_code == 200
    banks = {row["code"]: row["name"] for row in resp.json()}
    assert banks["40002"] == "Banamex"
    assert banks["40127"] == "Azteca"


async def test_cep_service_rejects_unknown_bank():
    with pytest.raises(CepValidationError) as exc:
        await validate_transfer(
            clave_rastreo="ABC12345",
            sender_bank="99999",
            receiver_bank="40002",
            receiver_account="012180004643051249",
            amount_cents=10000,
            transfer_date=date.today(),
        )
    assert exc.value.status == "invalid_bank"


async def _fake_save_document(file):
    return "/static/uploads/comprobante.webp"


def _fake_record(
    status="high",
    extracted=None,
    issues=None,
    entity_id=None,
    summary=None,
):
    from types import SimpleNamespace

    return SimpleNamespace(
        status=status,
        extracted=extracted or {},
        issues=issues or [],
        error=None,
        entity_id=entity_id,
        summary=summary,
    )


async def test_receipt_upload_approves_order(client, db_session, monkeypatch):
    token = await _register(client, "cep7@test.com")
    await _apicep_settings(db_session)
    order = await _order(db_session, token)
    monkeypatch.setattr(orders_module, "save_document", _fake_save_document)

    async def fake_create(*args, **kwargs):
        return _fake_record(
            extracted={
                "trackingKey": "MBAN0100241123456789",
                "senderBank": "BBVA MEXICO",
                "amount": 100.0,
                "validation": {
                    "banxicoConfirmed": True,
                    "cepStatus": "LIQUIDADO",
                    "cepDetails": {"trackingKey": "MBAN0100241123456789"},
                },
            }
        )

    monkeypatch.setattr(orders_module, "create_and_validate", fake_create)

    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer-receipt",
        headers=_headers(token),
        files={"file": ("comprobante.png", b"fake-image", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "approved"

    await db_session.refresh(order)
    assert order.payment_status == "approved"
    assert order.cep_status == "valid"
    assert order.transfer_tracking_key == "MBAN0100241123456789"
    assert order.cep_receiver_bank == "40012"
    assert order.cep_sender_bank == "BBVA MEXICO"


async def test_receipt_upload_rejects_unconfirmed(client, db_session, monkeypatch):
    token = await _register(client, "cep8@test.com")
    await _apicep_settings(db_session)
    order = await _order(db_session, token)
    monkeypatch.setattr(orders_module, "save_document", _fake_save_document)

    async def fake_create(*args, **kwargs):
        return _fake_record(
            status="low",
            extracted={"validation": {"banxicoConfirmed": False}},
            issues=["apiCEP no confirmó la transferencia con Banxico."],
        )

    monkeypatch.setattr(orders_module, "create_and_validate", fake_create)

    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer-receipt",
        headers=_headers(token),
        files={"file": ("comprobante.png", b"fake-image", "image/png")},
    )
    assert resp.status_code == 422
    assert "apiCEP" in resp.json()["detail"]

    await db_session.refresh(order)
    assert order.payment_status == "pending"


async def test_receipt_upload_requires_apicep(client, db_session):
    token = await _register(client, "cep9@test.com")
    await _settings(db_session)
    order = await _order(db_session, token)
    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer-receipt",
        headers=_headers(token),
        files={"file": ("comprobante.png", b"fake-image", "image/png")},
    )
    assert resp.status_code == 400


def _apicep_payload(**overrides):
    data = {
        "status": "valid",
        "confidence": 0.98,
        "extracted": {
            "trackingKey": "MBAN0100241123456789",
            "senderBank": "BBVA MEXICO",
            "amount": 100.0,
            "date": "2026-11-23",
        },
        "validation": {
            "banxicoConfirmed": True,
            "cepStatus": "LIQUIDADO",
            "cepPreviouslyValidated": False,
            "cepDetails": {"trackingKey": "MBAN0100241123456789"},
        },
    }
    data.update(overrides)
    return data


async def _receipt_record(db_session) -> ReceiptValidation:
    record = ReceiptValidation(
        entity_type="order_transfer",
        entity_id=uuid.uuid4(),
        file_url="/static/uploads/comprobante.webp",
        expected_kind="transfer_receipt",
        expected_amount=Decimal("100.00"),
        status="review",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def test_receipt_service_approves_with_apicep(db_session, monkeypatch):
    await _apicep_settings(db_session)
    record = await _receipt_record(db_session)

    async def fake_validate(db, *, file_url, expected_amount=None):
        return _apicep_payload()

    monkeypatch.setattr(rvs, "banxico_open", lambda: True)
    monkeypatch.setattr(rvs, "validate_apicep_receipt", fake_validate)
    result = await rvs.revalidate_receipt(db_session, record)

    assert result.provider == "apicep"
    assert result.status == "high"
    assert result.confidence == 100
    assert result.extracted["trackingKey"] == "MBAN0100241123456789"


async def test_receipt_service_rejects_reused_cep(db_session, monkeypatch):
    await _apicep_settings(db_session)
    record = await _receipt_record(db_session)

    async def fake_validate(db, *, file_url, expected_amount=None):
        payload = _apicep_payload()
        payload["validation"]["cepPreviouslyValidated"] = True
        return payload

    monkeypatch.setattr(rvs, "banxico_open", lambda: True)
    monkeypatch.setattr(rvs, "validate_apicep_receipt", fake_validate)
    result = await rvs.revalidate_receipt(db_session, record)

    assert result.status == "review"
    assert any("ya fue validado" in issue for issue in result.issues)


async def test_admin_approval_settles_order_transfer(client, db_session):
    admin = await _register(client, "cepadmin@test.com")
    user = await db_session.scalar(
        select(User).where(User.email == "cepadmin@test.com")
    )
    user.is_superuser = True
    await db_session.commit()

    token = await _register(client, "cep10@test.com")
    order = await _order(db_session, token)
    record = ReceiptValidation(
        entity_type="order_transfer",
        entity_id=order.id,
        file_url="/static/uploads/comprobante.webp",
        expected_kind="transfer_receipt",
        expected_amount=order.total,
        status="review",
        extracted=_apicep_payload()["extracted"]
        | {"validation": _apicep_payload()["validation"]},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    resp = await client.post(
        f"/api/v1/admin/receipts/{record.id}/approve",
        headers=_headers(admin),
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(order)
    assert order.payment_status == "approved"
    assert order.cep_status == "valid"
    assert order.transfer_tracking_key == "MBAN0100241123456789"


async def _fallback_settings(db_session, fallback="true", cap="200.0"):
    await _apicep_settings(db_session)
    db_session.add_all([
        Setting(key="RECEIPT_GEMINI_FALLBACK_ENABLED", value=fallback),
        Setting(key="RECEIPT_AUTO_APPROVE_MAX_AMOUNT", value=cap),
        Setting(key="RECEIPT_SAME_BANK_MAX_AMOUNT", value=cap),
        Setting(key="RECEIPT_GEMINI_MIN_CONFIDENCE", value="95"),
        Setting(key="GEMINI_API_KEY", value="gemini_test_key"),
    ])
    await db_session.commit()


def _fake_gemini(total, confidence=97):
    async def fake(db, record):
        record.provider = "gemini"
        record.document_type = rvs.TRANSFER
        record.confidence = confidence
        record.status = "high" if confidence >= 95 else "review"
        record.issues = []
        record.extracted = {
            "total": total,
            "recipient": "012180004643051249",
            "_checks": {
                "amount_ok": True,
                "date_ok": True,
                "recipient_ok": True,
                "fields_ok": True,
            },
        }
        return record

    return fake


async def test_fallback_preapproves_under_cap(db_session, monkeypatch):
    await _fallback_settings(db_session)
    record = await _receipt_record(db_session)
    record.expected_date = datetime.now(timezone.utc)
    record.expected_recipient = "012180004643051249"
    await db_session.commit()

    monkeypatch.setattr(rvs, "banxico_open", lambda: False)
    monkeypatch.setattr(rvs, "_validate_with_gemini", _fake_gemini(100.0))
    result = await rvs.revalidate_receipt(db_session, record)

    assert result.status == "preapproved"
    assert result.extracted["_preapproved"] is True


async def test_fallback_reviews_over_cap(db_session, monkeypatch):
    await _fallback_settings(db_session, cap="200.0")
    record = await _receipt_record(db_session)
    record.expected_amount = Decimal("250.00")
    record.expected_date = datetime.now(timezone.utc)
    record.expected_recipient = "012180004643051249"
    await db_session.commit()

    monkeypatch.setattr(rvs, "banxico_open", lambda: False)
    monkeypatch.setattr(rvs, "_validate_with_gemini", _fake_gemini(250.0))
    result = await rvs.revalidate_receipt(db_session, record)

    assert result.status == "review"
    assert any("límite" in issue for issue in result.issues)


async def test_fallback_disabled_outside_hours_pending(db_session, monkeypatch):
    await _fallback_settings(db_session, fallback="false")
    record = await _receipt_record(db_session)

    monkeypatch.setattr(rvs, "banxico_open", lambda: False)
    result = await rvs.revalidate_receipt(db_session, record)

    assert result.status == "pending_cep"
    assert result.provider == "apicep"


async def test_same_bank_preapproves_with_gemini(db_session, monkeypatch):
    await _fallback_settings(db_session)
    record = await _receipt_record(db_session)
    record.expected_date = datetime.now(timezone.utc)
    record.expected_recipient = "012180004643051249"
    await db_session.commit()

    async def same_bank_error(db, *, file_url, expected_amount=None):
        raise ApiCepError(
            "error",
            "El banco emisor y el banco receptor no pueden ser la misma "
            "institución. Las transferencias SPEI deben ser entre instituciones "
            "distintas.",
        )

    monkeypatch.setattr(rvs, "banxico_open", lambda: True)
    monkeypatch.setattr(rvs, "validate_apicep_receipt", same_bank_error)
    monkeypatch.setattr(rvs, "_validate_with_gemini", _fake_gemini(100.0))
    result = await rvs.revalidate_receipt(db_session, record)

    assert result.status == "preapproved"
    assert result.extracted["_same_bank"] is True


async def test_fallback_preserves_gemini_error(db_session, monkeypatch):
    await _fallback_settings(db_session)
    record = await _receipt_record(db_session)
    record.expected_date = datetime.now(timezone.utc)
    record.expected_recipient = "012180004643051249"
    await db_session.commit()

    async def fake_gemini(db, rec):
        rec.provider = "gemini"
        rec.document_type = None
        rec.confidence = 0
        rec.status = "low"
        rec.issues = ["Gemini respondió 503"]
        rec.error = "Gemini respondió 503"
        rec.extracted = {}
        return rec

    monkeypatch.setattr(rvs, "banxico_open", lambda: False)
    monkeypatch.setattr(rvs, "_validate_with_gemini", fake_gemini)
    result = await rvs.revalidate_receipt(db_session, record)

    assert result.status == "review"
    assert result.error == "Gemini respondió 503"
    assert any("503" in issue for issue in result.issues)


async def test_charge_failed_transfer_adds_pending_balance(
    client, db_session, monkeypatch
):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ots, "notify_admin_transfer_failed", noop)
    monkeypatch.setattr(ots, "send_to_user", noop)
    monkeypatch.setattr(ots, "send_email", noop)

    token = await _register(client, "cep11@test.com")
    order = await _order(db_session, token, total="150.00")
    order.status = "preparing"
    await db_session.commit()

    record = ReceiptValidation(
        entity_type="order_transfer",
        entity_id=order.id,
        file_url="/static/uploads/comprobante.webp",
        expected_kind="transfer_receipt",
        expected_amount=order.total,
        status="preapproved",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    customer = await db_session.scalar(
        select(User).where(User.id == order.user_id)
    )
    before = Decimal(customer.pending_balance or 0)
    await ots.charge_failed_transfer(db_session, record, "No confirmado")
    await db_session.refresh(customer)
    await db_session.refresh(order)

    assert customer.pending_balance == before + Decimal("150.00")
    assert order.cep_status == "failed"
    assert record.extracted["charged_to_balance"] is True


async def test_business_cannot_prepare_unpaid_transfer(client, db_session):
    token = await _register(client, "cep12@test.com")
    order = await _order(db_session, token)
    resp = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        headers=_headers(token),
        json={"status": "confirmed"},
    )
    assert resp.status_code == 409
    assert "no está confirmado" in resp.json()["detail"].lower()


async def test_receipt_upload_preapproved_marks_paid(
    client, db_session, monkeypatch
):
    token = await _register(client, "cep13@test.com")
    await _apicep_settings(db_session)
    order = await _order(db_session, token)
    monkeypatch.setattr(orders_module, "save_document", _fake_save_document)

    async def fake_create(*args, **kwargs):
        return _fake_record(
            status="preapproved",
            entity_id=order.id,
            extracted={"_preapproved": True, "_same_bank": False},
        )

    monkeypatch.setattr(orders_module, "create_and_validate", fake_create)
    monkeypatch.setattr(
        orders_module, "schedule_admin_transfer_review", lambda *a, **k: None
    )

    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer-receipt",
        headers=_headers(token),
        files={"file": ("comprobante.png", b"fake-image", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cep_status"] == "preapproved"

    await db_session.refresh(order)
    assert order.payment_status == "approved"
    assert order.cep_status == "preapproved"


async def test_receipt_upload_pending_cep_stays_unpaid(
    client, db_session, monkeypatch
):
    token = await _register(client, "cep14@test.com")
    await _apicep_settings(db_session)
    order = await _order(db_session, token)
    monkeypatch.setattr(orders_module, "save_document", _fake_save_document)

    async def fake_create(*args, **kwargs):
        return _fake_record(
            status="pending_cep",
            entity_id=order.id,
            summary="Pendiente de Banxico.",
        )

    monkeypatch.setattr(orders_module, "create_and_validate", fake_create)

    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer-receipt",
        headers=_headers(token),
        files={"file": ("comprobante.png", b"fake-image", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "pending"

    await db_session.refresh(order)
    assert order.payment_status == "pending"
    assert order.cep_status == "pending_cep"


async def test_receipt_upload_review_notifies_admin(
    client, db_session, monkeypatch
):
    token = await _register(client, "cep15@test.com")
    await _apicep_settings(db_session)
    order = await _order(db_session, token)
    monkeypatch.setattr(orders_module, "save_document", _fake_save_document)
    calls = []

    async def fake_create(*args, **kwargs):
        return _fake_record(
            status="review",
            entity_id=order.id,
            summary="Pago en revisión.",
        )

    monkeypatch.setattr(orders_module, "create_and_validate", fake_create)
    monkeypatch.setattr(
        orders_module,
        "schedule_admin_transfer_review",
        lambda *args, **kwargs: calls.append(args),
    )

    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer-receipt",
        headers=_headers(token),
        files={"file": ("comprobante.png", b"fake-image", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cep_status"] == "review"
    assert calls

    await db_session.refresh(order)
    assert order.payment_status == "pending"
    assert order.cep_status == "review"


def _make_clabe(prefix: str, body: str) -> str:
    first17 = (prefix + body)[:17]
    weights = [3, 7, 1] * 6
    total = sum(int(d) * weights[i] for i, d in enumerate(first17))
    return first17 + str((10 - (total % 10)) % 10)


async def _second_account(db_session, clabe_value: str) -> None:
    db_session.add_all([
        Setting(key="BANK_NAME_2", value="Banco Azteca"),
        Setting(key="BANK_ACCOUNT_HOLDER_2", value="TuPedidoJR"),
        Setting(key="BANK_CLABE_2", value=clabe_value),
    ])
    await db_session.commit()


async def test_bank_details_includes_second_account(client, db_session):
    token = await _register(client, "cep16@test.com")
    await _settings(db_session)
    azteca = _make_clabe("127", "01000000000000")
    await _second_account(db_session, azteca)

    resp = await client.get(
        "/api/v1/payments/bank-details", headers=_headers(token)
    )
    assert resp.status_code == 200, resp.text
    accounts = resp.json()["accounts"]
    assert {account["bank_code"] for account in accounts} == {"40012", "40127"}
    assert any(account["clabe"] == azteca for account in accounts)


async def test_manual_cep_uses_other_bank_account(
    client, db_session, monkeypatch
):
    token = await _register(client, "cep17@test.com")
    await _settings(db_session)
    azteca = _make_clabe("127", "01000000000000")
    await _second_account(db_session, azteca)
    order = await _order(db_session, token)
    calls = []
    monkeypatch.setattr(orders_module, "validate_transfer", _fake_validate(calls))

    resp = await client.post(
        f"/api/v1/orders/{order.id}/validate-transfer",
        headers=_headers(token),
        json={
            "clave_rastreo": "ABC12345",
            "sender_bank": "40012",
            "transfer_date": str(date.today()),
        },
    )
    assert resp.status_code == 200, resp.text
    assert calls[0]["receiver_bank"] == "40127"
    assert calls[0]["receiver_account"] == azteca

    await db_session.refresh(order)
    assert order.cep_receiver_bank == "40127"


async def test_apicep_uses_potential_beneficiaries(db_session, monkeypatch):
    await _apicep_settings(db_session)
    azteca = _make_clabe("127", "01000000000000")
    await _second_account(db_session, azteca)
    captured = {}

    class FakeResponse:
        status_code = 400
        text = "{}"

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(api_cep_service.httpx, "AsyncClient", FakeClient)

    with pytest.raises(api_cep_service.ApiCepError):
        await api_cep_service.validate_receipt(
            db_session, file_url="/static/uploads/comprobante.webp"
        )

    accounts = captured["payload"]["potentialBeneficiaries"]
    assert len(accounts) == 2
    assert {account["bank"] for account in accounts} == {
        "BBVA MEXICO",
        "AZTECA",
    }


async def test_business_list_hides_unpaid_transfer(client, db_session):
    token = await _register(client, "cep18@test.com")
    order = await _order(db_session, token)

    hidden = await client.get(
        f"/api/v1/restaurants/{order.restaurant_id}/orders",
        headers=_headers(token),
    )
    assert hidden.status_code == 200, hidden.text
    assert all(row["id"] != str(order.id) for row in hidden.json())

    order.payment_status = "approved"
    await db_session.commit()

    visible = await client.get(
        f"/api/v1/restaurants/{order.restaurant_id}/orders",
        headers=_headers(token),
    )
    assert visible.status_code == 200, visible.text
    assert any(row["id"] == str(order.id) for row in visible.json())


async def test_business_list_shows_cash_order(client, db_session):
    token = await _register(client, "cep19@test.com")
    order = await _order(db_session, token)
    order.payment_method = "cash"
    order.payment_status = "pending"
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/restaurants/{order.restaurant_id}/orders",
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert any(row["id"] == str(order.id) for row in resp.json())


async def test_business_cannot_confirm_unpaid_transfer(client, db_session):
    token = await _register(client, "cep20@test.com")
    order = await _order(db_session, token)

    resp = await client.patch(
        f"/api/v1/restaurants/{order.restaurant_id}/orders/{order.id}/status",
        headers=_headers(token),
        json={"status": "confirmed"},
    )
    assert resp.status_code == 409
    assert "no está confirmado" in resp.json()["detail"].lower()


async def test_payment_config_warns_when_no_validation(
    client, db_session, monkeypatch
):
    await _apicep_settings(db_session)
    db_session.add(
        Setting(key="RECEIPT_GEMINI_FALLBACK_ENABLED", value="true")
    )
    await db_session.commit()
    monkeypatch.setattr(payments_module, "banxico_open", lambda: False)

    resp = await client.get("/api/v1/payments/config")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["banxico_open"] is False
    assert data["apicep_ready"] is True
    assert data["gemini_ready"] is False
    assert data["transfer_auto_validation_available"] is False
    assert data["transfer_validation_message"]


async def test_payment_config_with_gemini_fallback(
    client, db_session, monkeypatch
):
    await _apicep_settings(db_session)
    db_session.add_all([
        Setting(key="RECEIPT_GEMINI_FALLBACK_ENABLED", value="true"),
        Setting(key="GEMINI_API_KEY", value="gemini_test_key"),
    ])
    await db_session.commit()
    monkeypatch.setattr(payments_module, "banxico_open", lambda: False)

    resp = await client.get("/api/v1/payments/config")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["gemini_ready"] is True
    assert data["transfer_auto_validation_available"] is True


async def test_switch_unpaid_transfer_to_cash(
    client, db_session, monkeypatch
):
    token = await _register(client, "cep21@test.com")
    order = await _order(db_session, token)
    monkeypatch.setattr(
        orders_module, "schedule_order_release", lambda *args, **kwargs: None
    )

    resp = await client.post(
        f"/api/v1/orders/{order.id}/switch-to-cash",
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_method"] == "cash"

    await db_session.refresh(order)
    assert order.payment_method == "cash"
    assert order.cep_status is None

    business = await client.get(
        f"/api/v1/restaurants/{order.restaurant_id}/orders",
        headers=_headers(token),
    )
    assert business.status_code == 200, business.text
    assert any(row["id"] == str(order.id) for row in business.json())


async def test_cannot_switch_paid_transfer_to_cash(client, db_session):
    token = await _register(client, "cep22@test.com")
    order = await _order(db_session, token)
    order.payment_status = "approved"
    order.cep_status = "valid"
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/switch-to-cash",
        headers=_headers(token),
    )
    assert resp.status_code == 400
