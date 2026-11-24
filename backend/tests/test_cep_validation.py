"""Validación de transferencias SPEI con el CEP de Banxico."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.v1 import orders as orders_module
from app.core.security import decode_access_token
from app.models.order import Order
from app.models.receipt_validation import ReceiptValidation
from app.models.restaurant import Restaurant
from app.models.setting import Setting
from app.models.user import User
from app.services import receipt_validation_service as rvs
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


def _fake_record(status="high", extracted=None, issues=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        status=status,
        extracted=extracted or {},
        issues=issues or [],
        error=None,
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
