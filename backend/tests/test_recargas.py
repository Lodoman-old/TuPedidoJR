"""Recargas manuales: cobro en efectivo, deuda y reembolso."""
import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def courier_account(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Courier Recargas", "email": "courier-rec@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    db_session.add(DeliveryPerson(user_id=user_id, vehicle_type="motorcycle", is_available=True))
    await db_session.commit()
    return token


@pytest.fixture
async def admin_account(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Recargas", "email": "admin-rec@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


async def test_courier_payout_detail_works(
    client: AsyncClient, db_session, courier_account, admin_account
):
    user_id = uuid.UUID(decode_access_token(courier_account)["sub"])
    dp = (await db_session.execute(
        DeliveryPerson.__table__.select().where(DeliveryPerson.user_id == user_id)
    )).first()
    resp = await client.get(
        f"/api/v1/admin/payouts/couriers/{dp.id}/detail",
        headers=_headers(admin_account),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"]


async def test_cash_recarga_creates_debt_and_commission(
    client: AsyncClient, db_session, courier_account
):
    resp = await client.post(
        "/api/v1/recargas",
        json={"company": "Telcel", "phone": "4121234567", "amount": 50, "payment_method": "cash"},
        headers=_headers(courier_account),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["fee"] == "2.00"
    assert data["total"] == "52.00"

    user_id = uuid.UUID(decode_access_token(courier_account)["sub"])
    dp = (await db_session.execute(
        DeliveryPerson.__table__.select().where(DeliveryPerson.user_id == user_id)
    )).first()
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("50.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("2.00")


async def test_refund_reverses_debt_and_commission(
    client: AsyncClient, db_session, courier_account, admin_account
):
    created = await client.post(
        "/api/v1/recargas",
        json={"company": "Telcel", "phone": "4121234567", "amount": 100, "payment_method": "cash"},
        headers=_headers(courier_account),
    )
    recarga_id = created.json()["id"]

    failed = await client.post(
        f"/api/v1/admin/recargas/{recarga_id}/fail",
        json={"refund": True, "error_message": "Sin saldo con el proveedor"},
        headers=_headers(admin_account),
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "refunded"
    assert failed.json()["payment_status"] == "refunded"

    user_id = uuid.UUID(decode_access_token(courier_account)["sub"])
    dp = (await db_session.execute(
        DeliveryPerson.__table__.select().where(DeliveryPerson.user_id == user_id)
    )).first()
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("0.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("0.00")
