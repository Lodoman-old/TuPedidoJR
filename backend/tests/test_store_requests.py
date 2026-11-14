"""Tests for stores, catalogs and custom product requests."""

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.restaurant import Restaurant
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Dueño Tienda", "email": "owner-tienda@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Tienda", "email": "cliente-tienda@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def restaurant(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Restaurante Prueba",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 1",
        is_open=True,
        rating=4.5,
        delivery_radius_m=5000,
        delivery_fee=20.00,
        business_type="restaurant",
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    await db_session.commit()
    return resto


@pytest.fixture
async def store(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    store = Restaurant(
        id=uuid.uuid4(),
        name="Abarrotes Prueba",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.995 20.645)",
        address="Calle 2",
        is_open=True,
        rating=4.7,
        delivery_radius_m=5000,
        delivery_fee=20.00,
        business_type="store",
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(store)
    await db_session.commit()
    return store


class TestStoreListing:
    async def test_store_pages_load(self, client):
        page = await client.get("/web/restaurants?type=store")
        assert page.status_code == 200
        assert "Tiendas" in page.text
        requests_page = await client.get("/web/store-requests")
        assert requests_page.status_code == 200
        assert "Mis solicitudes de producto" in requests_page.text

    async def test_default_list_only_restaurants(self, client, restaurant, store):
        resp = await client.get("/api/v1/restaurants")
        assert resp.status_code == 200
        names = [row["name"] for row in resp.json()]
        assert "Restaurante Prueba" in names
        assert "Abarrotes Prueba" not in names

    async def test_store_filter_returns_stores(self, client, restaurant, store):
        resp = await client.get("/api/v1/restaurants?business_type=store")
        assert resp.status_code == 200
        data = resp.json()
        assert [row["name"] for row in data] == ["Abarrotes Prueba"]
        assert data[0]["business_type"] == "store"


class TestStoreRequests:
    async def _create_request(self, client, store, customer_token):
        resp = await client.post(
            f"/api/v1/restaurants/{store.id}/requests",
            json={
                "description": "2 kg de azúcar",
                "quantity": 2,
                "budget": 100,
                "delivery_address": "Calle 5 de Mayo 209",
                "delivery_location": {"lat": 20.6449, "lng": -100.9945},
                "payment_method": "cash",
                "notes": "Marca no importa",
            },
            headers=_headers(customer_token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def test_quote_and_convert_to_order(
        self, client, store, owner_token, customer_token,
    ):
        request = await self._create_request(client, store, customer_token)

        listed = await client.get(
            f"/api/v1/restaurants/{store.id}/requests",
            headers=_headers(owner_token),
        )
        assert listed.status_code == 200
        assert listed.json()[0]["description"] == "2 kg de azúcar"

        quoted = await client.patch(
            f"/api/v1/restaurants/{store.id}/requests/{request['id']}/respond",
            json={"status": "quoted", "quoted_price": 50, "store_notes": "Sí hay"},
            headers=_headers(owner_token),
        )
        assert quoted.status_code == 200, quoted.text
        assert quoted.json()["status"] == "quoted"

        confirmed = await client.post(
            f"/api/v1/store-requests/{request['id']}/confirm",
            headers=_headers(customer_token),
        )
        assert confirmed.status_code == 200, confirmed.text
        data = confirmed.json()
        assert data["status"] == "converted"
        assert data["order_id"]

        order = await client.get(
            f"/api/v1/orders/{data['order_id']}",
            headers=_headers(customer_token),
        )
        assert order.status_code == 200, order.text
        order_data = order.json()
        assert order_data["items"][0]["name"] == "2 kg de azúcar"
        assert order_data["items"][0]["quantity"] == 2
        assert float(order_data["subtotal"]) == 100
        assert float(order_data["platform_commission"]) == 5
        assert float(order_data["flat_usage_fee"]) == 5
        assert float(order_data["total"]) == 130

    async def test_store_can_reject_request(
        self, client, store, owner_token, customer_token,
    ):
        request = await self._create_request(client, store, customer_token)
        rejected = await client.patch(
            f"/api/v1/restaurants/{store.id}/requests/{request['id']}/respond",
            json={"status": "rejected", "store_notes": "No hay"},
            headers=_headers(owner_token),
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

    async def test_customer_cannot_respond_for_store(
        self, client, store, customer_token,
    ):
        request = await self._create_request(client, store, customer_token)
        resp = await client.patch(
            f"/api/v1/restaurants/{store.id}/requests/{request['id']}/respond",
            json={"status": "quoted", "quoted_price": 50},
            headers=_headers(customer_token),
        )
        assert resp.status_code == 403
