"""Límites de servicios simultáneos por repartidor."""

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.services.setting_service import set_setting


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Límites", "email": "limits-customer@test.com", "password": "pass1234",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def courier(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Repartidor Límites", "email": "limits-courier@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user_id = decode_access_token(token)["sub"]
    dp = DeliveryPerson(user_id=user_id, vehicle_type="motorcycle", is_available=True)
    db_session.add(dp)
    await db_session.commit()
    await db_session.refresh(dp)
    return token, dp


@pytest.fixture
async def restaurant(db_session, customer_token):
    owner_id = decode_access_token(customer_token)["sub"]
    row = Restaurant(
        id=uuid.uuid4(),
        name="Resto Límites",
        owner_id=owner_id,
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Calle 1",
        delivery_mode="platform",
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(row)
    db_session.add(MenuItem(
        id=uuid.uuid4(), restaurant_id=row.id, name="Item", price=50,
        preparation_time_min=5, is_available=True,
    ))
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _create_ready_order(db_session, customer_token, restaurant) -> Order:
    order = Order(
        user_id=decode_access_token(customer_token)["sub"],
        restaurant_id=restaurant.id,
        status="ready",
        subtotal=100,
        delivery_fee=20,
        total=120,
        delivery_address="Calle 1",
        delivery_location="SRID=4326;POINT(-99.13 19.43)",
        delivery_earnings=20,
        delivery_mode="platform",
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


class TestCourierLimits:
    async def test_accept_keeps_courier_available(
        self, client: AsyncClient, db_session, customer_token, courier, restaurant,
    ):
        token, dp = courier
        order = await _create_ready_order(db_session, customer_token, restaurant)

        resp = await client.post(f"/api/v1/delivery/accept/{order.id}", headers=_headers(token))
        assert resp.status_code == 200
        await db_session.refresh(dp)
        assert dp.is_available is True

    async def test_blocks_sixth_service(
        self, client: AsyncClient, db_session, customer_token, courier, restaurant,
    ):
        token, _dp = courier
        for _ in range(5):
            order = await _create_ready_order(db_session, customer_token, restaurant)
            resp = await client.post(f"/api/v1/delivery/accept/{order.id}", headers=_headers(token))
            assert resp.status_code == 200, resp.text

        extra = await _create_ready_order(db_session, customer_token, restaurant)
        resp = await client.post(f"/api/v1/delivery/accept/{extra.id}", headers=_headers(token))
        assert resp.status_code == 400
        assert "límite" in resp.json()["detail"].lower()

    async def test_limits_endpoint(
        self, client: AsyncClient, db_session, customer_token, courier, restaurant,
    ):
        token, _dp = courier
        for _ in range(2):
            order = await _create_ready_order(db_session, customer_token, restaurant)
            resp = await client.post(f"/api/v1/delivery/accept/{order.id}", headers=_headers(token))
            assert resp.status_code == 200

        resp = await client.get("/api/v1/delivery/limits", headers=_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] == 2
        assert data["max"] >= 2
        assert data["can_accept"] is True

    async def test_custom_limits(
        self, client: AsyncClient, db_session, customer_token, courier, restaurant,
    ):
        token, _dp = courier
        await set_setting(db_session, "MAX_ACTIVE_SERVICES", "3")
        await set_setting(db_session, "WARN_ACTIVE_SERVICES", "2")
        await db_session.commit()

        resp = await client.get("/api/v1/delivery/limits", headers=_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["max"] == 3
        assert data["warn"] == 2

        for _ in range(3):
            order = await _create_ready_order(db_session, customer_token, restaurant)
            resp = await client.post(f"/api/v1/delivery/accept/{order.id}", headers=_headers(token))
            assert resp.status_code == 200

        extra = await _create_ready_order(db_session, customer_token, restaurant)
        resp = await client.post(f"/api/v1/delivery/accept/{extra.id}", headers=_headers(token))
        assert resp.status_code == 400
