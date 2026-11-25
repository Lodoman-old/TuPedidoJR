"""Pruebas del pago directo del saldo pendiente."""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from httpx import AsyncClient
from sqlalchemy import select

from app.api.v1 import balance as balance_module
from app.core.security import decode_access_token
from app.models.balance_payment import BalancePayment
from app.models.receipt_validation import ReceiptValidation
from app.models.setting import Setting
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str, phone: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Cliente Saldo",
            "email": email,
            "phone": phone,
            "password": "pass1234",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _user(db_session, token: str) -> User:
    return await db_session.get(
        User, uuid.UUID(decode_access_token(token)["sub"])
    )


async def _balance(db_session, token: str, amount: str = "100.00") -> User:
    user = await _user(db_session, token)
    user.pending_balance = Decimal(amount)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _settings(db_session) -> None:
    db_session.add_all([
        Setting(key="CEP_ENABLED", value="true"),
        Setting(key="BANK_CLABE", value="012180004643051249"),
        Setting(key="RECEIPT_VALIDATION_ENABLED", value="true"),
        Setting(key="RECEIPT_VALIDATION_PROVIDER", value="apicep"),
        Setting(key="APICEP_API_KEY", value="apicep_test_key"),
        Setting(key="APP_PUBLIC_URL", value="https://tupedidojr.com"),
    ])
    await db_session.commit()


async def test_balance_manual_cep_pays(client, db_session, monkeypatch):
    token = await _register(client, "balance1@test.com", "4110000001")
    await _settings(db_session)
    user = await _balance(db_session, token)

    created = await client.post(
        "/api/v1/balance/payments", headers=_headers(token)
    )
    assert created.status_code == 200, created.text
    payment = created.json()["payment"]
    assert Decimal(payment["amount"]) == Decimal("100.00")
    assert payment["reference"]

    async def fake_validate(**kwargs):
        return {
            "status": "valid",
            "clave_rastreo": kwargs["clave_rastreo"],
            "monto": "100.00",
            "monto_centavos": kwargs["amount_cents"],
            "emisor": kwargs["sender_bank"],
            "receptor": kwargs["receiver_bank"],
            "beneficiario": kwargs["receiver_account"],
        }

    monkeypatch.setattr(balance_module, "validate_transfer", fake_validate)

    resp = await client.post(
        f"/api/v1/balance/payments/{payment['id']}/validate-transfer",
        headers=_headers(token),
        json={
            "clave_rastreo": "BAL12345",
            "sender_bank": "40014",
            "transfer_date": str(date.today()),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "approved"

    await db_session.refresh(user)
    assert Decimal(user.pending_balance or 0) == Decimal("0.00")
    saved = await db_session.get(BalancePayment, uuid.UUID(payment["id"]))
    assert saved.status == "approved"
    assert saved.transfer_tracking_key == "BAL12345"


async def test_balance_receipt_pays(client, db_session, monkeypatch):
    token = await _register(client, "balance2@test.com", "4110000002")
    await _settings(db_session)
    user = await _balance(db_session, token)

    created = await client.post(
        "/api/v1/balance/payments", headers=_headers(token)
    )
    payment = created.json()["payment"]

    async def fake_save(file):
        return "/static/uploads/balance_receipt.webp"

    async def fake_create(*args, **kwargs):
        return SimpleNamespace(
            status="high",
            extracted={
                "trackingKey": "BAL98765",
                "senderBank": "BBVA MEXICO",
                "validation": {
                    "cepHint": True,
                    "cepDetails": {"receiverBank": "BANAMEX"},
                },
            },
            issues=[],
            error=None,
        )

    monkeypatch.setattr(balance_module, "save_document", fake_save)
    monkeypatch.setattr(balance_module, "create_and_validate", fake_create)
    monkeypatch.setattr(
        "app.services.cep_validation_service.banxico_open", lambda: True
    )

    resp = await client.post(
        f"/api/v1/balance/payments/{payment['id']}/validate-receipt",
        headers=_headers(token),
        files={"file": ("comprobante.png", b"fake-image", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "approved"

    await db_session.refresh(user)
    assert Decimal(user.pending_balance or 0) == Decimal("0.00")


async def test_admin_approves_balance_payment(client, db_session):
    admin = await _register(client, "balanceadmin@test.com", "4110000003")
    admin_user = await _user(db_session, admin)
    admin_user.is_superuser = True
    await db_session.commit()

    token = await _register(client, "balance3@test.com", "4110000004")
    await _settings(db_session)
    user = await _balance(db_session, token)

    payment = BalancePayment(
        user_id=user.id,
        amount=Decimal("100.00"),
        status="review",
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    record = ReceiptValidation(
        entity_type="balance_payment",
        entity_id=payment.id,
        file_url="/static/uploads/balance_receipt.webp",
        expected_kind="transfer_receipt",
        expected_amount=payment.amount,
        status="review",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    resp = await client.post(
        f"/api/v1/admin/receipts/{record.id}/approve",
        headers=_headers(admin),
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(user)
    await db_session.refresh(payment)
    assert Decimal(user.pending_balance or 0) == Decimal("0.00")
    assert payment.status == "approved"
