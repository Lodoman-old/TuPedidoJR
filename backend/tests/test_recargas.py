"""Recargas: función en pausa y acciones sobre registros anteriores."""
import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant import Restaurant
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


async def test_standalone_cash_recarga_requires_order(
    client: AsyncClient, db_session, courier_account
):
    resp = await client.post(
        "/api/v1/recargas",
        json={"company": "Telcel", "phone": "4121234567", "amount": 50, "payment_method": "cash"},
        headers=_headers(courier_account),
    )
    assert resp.status_code == 400, resp.text
    assert "entregar un pedido" in resp.json()["detail"].lower()

    dp = await _courier(db_session, courier_account)
    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("0.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("0.00")


async def test_portal_transfer_recarga_still_paused(
    client: AsyncClient, courier_account
):
    resp = await client.post(
        "/api/v1/recargas",
        json={
            "company": "Telcel",
            "phone": "4121234567",
            "amount": 50,
            "payment_method": "transfer",
        },
        headers=_headers(courier_account),
    )
    assert resp.status_code == 503, resp.text
    assert "próximamente" in resp.json()["detail"].lower()


async def test_courier_can_offer_recarga_on_delivered_order(
    client: AsyncClient, db_session, courier_account
):
    dp = await _courier(db_session, courier_account)
    customer = User(
        name="Cliente Recarga",
        email="recarga-order-customer@test.com",
        password_hash="x",
        phone="4120000000",
    )
    db_session.add(customer)
    await db_session.flush()
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Negocio Recarga",
        owner_id=customer.id,
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Calle Prueba",
    )
    db_session.add(restaurant)
    await db_session.flush()
    order = Order(
        id=uuid.uuid4(),
        user_id=customer.id,
        restaurant_id=restaurant.id,
        delivery_person_id=dp.id,
        status="delivered",
        subtotal=Decimal("100.00"),
        delivery_fee=Decimal("10.00"),
        total=Decimal("110.00"),
        delivery_address="Calle Principal 123",
        delivery_location="SRID=4326;POINT(-99.14 19.44)",
        payment_method="cash",
        payment_status="pending",
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/recargas",
        json={
            "company": "Telcel",
            "phone": "4121234567",
            "amount": 50,
            "payment_method": "cash",
            "order_id": str(order.id),
        },
        headers=_headers(courier_account),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["fee"] == "2.00"
    assert data["total"] == "52.00"

    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("50.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("2.00")


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
