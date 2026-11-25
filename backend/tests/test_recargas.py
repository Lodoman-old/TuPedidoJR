"""Recargas: función en pausa y acciones sobre registros anteriores."""
import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.user import User
from app.services import recarga_service


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _courier(db_session, token: str) -> DeliveryPerson:
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    return await db_session.scalar(
        select(DeliveryPerson).where(DeliveryPerson.user_id == user_id)
    )


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
    dp = await _courier(db_session, courier_account)
    resp = await client.get(
        f"/api/v1/admin/payouts/couriers/{dp.id}/detail",
        headers=_headers(admin_account),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"]


async def test_recarga_requests_are_paused(
    client: AsyncClient, db_session, courier_account
):
    resp = await client.post(
        "/api/v1/recargas",
        json={"company": "Telcel", "phone": "4121234567", "amount": 50, "payment_method": "cash"},
        headers=_headers(courier_account),
    )
    assert resp.status_code == 503, resp.text
    assert "próximamente" in resp.json()["detail"].lower()

    dp = await _courier(db_session, courier_account)
    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("0.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("0.00")


async def test_refund_reverses_debt_and_commission(
    client: AsyncClient, db_session, courier_account, admin_account
):
    dp = await _courier(db_session, courier_account)
    recarga = await recarga_service.create_cash_recarga(
        db_session,
        dp,
        company="Telcel",
        phone="4121234567",
        amount=Decimal("100.00"),
    )
    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("100.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("2.00")

    failed = await client.post(
        f"/api/v1/admin/recargas/{recarga.id}/fail",
        json={"refund": True, "error_message": "Sin saldo con el proveedor"},
        headers=_headers(admin_account),
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "refunded"
    assert failed.json()["payment_status"] == "refunded"

    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("0.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("0.00")
