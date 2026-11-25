"""Pruebas del panel de transferencias pendientes."""
import uuid
from decimal import Decimal

from httpx import AsyncClient

from app.api.v1 import admin_transfers
from app.models.balance_payment import BalancePayment
from app.models.receipt_validation import ReceiptValidation
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str, phone: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Admin Transferencias",
            "email": email,
            "phone": phone,
            "password": "pass1234",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _superuser(client, db_session, email: str, phone: str) -> str:
    token = await _register(client, email, phone)
    from app.core.security import decode_access_token

    user = await db_session.get(
        User, uuid.UUID(decode_access_token(token)["sub"])
    )
    user.is_superuser = True
    await db_session.commit()
    return token


async def _customer(db_session, token: str) -> User:
    from app.core.security import decode_access_token

    return await db_session.get(
        User, uuid.UUID(decode_access_token(token)["sub"])
    )


async def _pending_balance_record(db_session, token: str):
    customer = await _customer(db_session, token)
    payment = BalancePayment(
        user_id=customer.id,
        amount=Decimal("100.00"),
        status="pending",
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    record = ReceiptValidation(
        entity_type="balance_payment",
        entity_id=payment.id,
        file_url="/static/uploads/comprobante.webp",
        expected_kind="transfer_receipt",
        expected_amount=Decimal("100.00"),
        status="review",
        summary="Pago en revisión.",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return payment, record


async def test_transfers_summary_totals_and_records(client, db_session):
    admin = await _superuser(client, db_session, "trans-admin@test.com", "4112000001")
    customer_token = await _register(
        client, "trans-customer@test.com", "4112000002"
    )
    _, record = await _pending_balance_record(db_session, customer_token)

    resp = await client.get(
        "/api/v1/admin/transfers/summary", headers=_headers(admin)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["totals"]["unresolved"] == 1
    assert data["totals"]["review"] == 1
    assert Decimal(data["totals"]["amount"]) == Decimal("100.00")
    assert len(data["records"]) == 1
    row = data["records"][0]
    assert row["receipt_id"] == str(record.id)
    assert row["status"] == "review"
    assert row["customer_phone"] == "524112000002"


async def test_transfers_revalidate_processes_records(
    client, db_session, monkeypatch
):
    admin = await _superuser(client, db_session, "trans-admin2@test.com", "4112000003")
    customer_token = await _register(
        client, "trans-customer2@test.com", "4112000004"
    )
    _, record = await _pending_balance_record(db_session, customer_token)

    async def fake_revalidate(db, row):
        row.status = "high"
        return row

    async def fake_settle(db, row, approved=True):
        return None

    monkeypatch.setattr(admin_transfers, "banxico_open", lambda: True)
    monkeypatch.setattr(admin_transfers, "revalidate_receipt", fake_revalidate)
    monkeypatch.setattr(
        admin_transfers, "settle_balance_payment_record", fake_settle
    )

    resp = await client.post(
        "/api/v1/admin/transfers/revalidate", headers=_headers(admin)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["processed"] == 1
    assert data["confirmed"] == 1
