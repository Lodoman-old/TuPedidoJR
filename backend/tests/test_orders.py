"""Tests for orders endpoints: create, list, detail, status, cancel."""

import uuid

import pytest
from httpx import AsyncClient

from app.models.menu_category import MenuCategory
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant


@pytest.fixture
async def user_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Order User", "email": "order@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def other_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Other User", "email": "other2@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def seeded_restaurant(db_session, user_token) -> tuple[Restaurant, MenuItem]:
    from app.core.security import decode_access_token
    payload = decode_access_token(user_token)

    rid = uuid.uuid4()
    r = Restaurant(
        id=rid, name="Order Resto", owner_id=payload["sub"],
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Addr", is_open=True, rating=4.0,
        delivery_radius_m=5000, delivery_fee=15.00,
    )
    db_session.add(r)

    item = MenuItem(id=uuid.uuid4(), restaurant_id=rid, name="Burger",
                    price=50.00, preparation_time_min=10, is_available=True)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(r)
    await db_session.refresh(item)
    return r, item


class TestPaymentConfig:
    async def test_cash_only_by_default(self, client: AsyncClient):
        resp = await client.get("/api/v1/payments/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cash_enabled"] is True
        assert data["mp_enabled"] is False
        assert data["transfer_enabled"] is False
        assert "loyalty_visible" in data
        assert "loyalty_value_per_point" in data


class TestOrderTracking:
    async def test_tracking_available_to_owner(
        self, client: AsyncClient, user_token, seeded_restaurant,
    ):
        resto, item = seeded_restaurant
        created = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.44, "lng": -99.14},
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert created.status_code == 201
        oid = created.json()["id"]

        resp = await client.get(
            f"/api/v1/orders/{oid}/tracking",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert len(data["timeline"]) == 7
        assert data["timeline"][0]["completed"] is True
        assert data["destination"] == {"lat": 19.44, "lng": -99.14}
        assert data["restaurant"] is not None
        assert data["eta_min"] >= 1

    async def test_tracking_forbidden_for_other_user(
        self, client: AsyncClient, user_token, other_token, seeded_restaurant,
    ):
        resto, item = seeded_restaurant
        created = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.44, "lng": -99.14},
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        oid = created.json()["id"]

        resp = await client.get(
            f"/api/v1/orders/{oid}/tracking",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


class TestCreateOrder:
    async def test_create_success(self, client: AsyncClient, user_token, seeded_restaurant):
        resto, item = seeded_restaurant
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 2}],
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert float(data["subtotal"]) == 115.0
        assert float(data["platform_commission"]) == 15.0
        # Delivery is at the restaurant, so the 6 km free radius applies and
        # the configured base fee (default 25.0) is charged.
        assert float(data["delivery_fee"]) == 25.0
        assert float(data["flat_usage_fee"]) == 5.0
        assert float(data["total"]) == 145.0
        assert len(data["items"]) == 1

    async def test_create_with_fixed_fee(self, client: AsyncClient, user_token, seeded_restaurant, db_session):
        resto, item = seeded_restaurant
        resto.commission_mode = "fixed"
        resto.fixed_fee = 5
        await db_session.commit()

        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 2}],
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        # Cuota fija: los precios del cliente no llevan markup y al restaurante
        # se le descuenta la cuota fija.
        assert float(data["subtotal"]) == 100.0
        assert float(data["platform_commission"]) == 5.0
        assert float(data["delivery_fee"]) == 25.0
        assert float(data["flat_usage_fee"]) == 5.0
        assert float(data["total"]) == 130.0

    async def test_create_with_mp_is_disabled(self, client: AsyncClient, user_token, seeded_restaurant):
        resto, item = seeded_restaurant
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
                "payment_method": "mp",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 400
        assert "Mercado Pago" in resp.json()["detail"]

    async def test_create_invalid_restaurant(self, client: AsyncClient, user_token):
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": "00000000-0000-0000-0000-000000000000",
                "items": [{"menu_item_id": "00000000-0000-0000-0000-000000000000", "quantity": 1}],
                "delivery_address": "Address 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 404

    async def test_create_invalid_item(self, client: AsyncClient, user_token, seeded_restaurant):
        resto, _ = seeded_restaurant
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": "00000000-0000-0000-0000-000000000000", "quantity": 1}],
                "delivery_address": "Address 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 400

    async def test_create_unauthorized(self, client: AsyncClient, seeded_restaurant):
        resto, item = seeded_restaurant
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Address 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
        )
        assert resp.status_code == 401


class TestListOrders:
    async def test_list_empty(self, client: AsyncClient, user_token):
        resp = await client.get("/api/v1/orders", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_own_orders(self, client: AsyncClient, user_token, seeded_restaurant):
        resto, item = seeded_restaurant
        await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Address 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.get("/api/v1/orders", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1


class TestGetOrder:
    async def _create_order(self, client, token, resto, item):
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Address 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.json()["id"]

    async def test_get_own_order(self, client: AsyncClient, user_token, seeded_restaurant):
        resto, item = seeded_restaurant
        order_id = await self._create_order(client, user_token, resto, item)
        resp = await client.get(f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        assert resp.json()["id"] == order_id

    async def test_get_other_order(self, client: AsyncClient, user_token, other_token, seeded_restaurant):
        resto, item = seeded_restaurant
        order_id = await self._create_order(client, user_token, resto, item)
        resp = await client.get(f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {other_token}"})
        assert resp.status_code == 403

    async def test_restaurant_owner_can_get_customer_order(
        self, client: AsyncClient, user_token, other_token, seeded_restaurant
    ):
        resto, item = seeded_restaurant
        order_id = await self._create_order(client, other_token, resto, item)
        resp = await client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == order_id

    async def test_get_not_found(self, client: AsyncClient, user_token):
        resp = await client.get(
            "/api/v1/orders/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 404


class TestCancelOrder:
    async def _create_order(self, client, token, resto, item):
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Address 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.json()["id"]

    async def test_cancel_pending(self, client: AsyncClient, user_token, seeded_restaurant):
        resto, item = seeded_restaurant
        order_id = await self._create_order(client, user_token, resto, item)
        resp = await client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    async def test_cancel_other_user(self, client: AsyncClient, user_token, other_token, seeded_restaurant):
        resto, item = seeded_restaurant
        order_id = await self._create_order(client, user_token, resto, item)
        resp = await client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_cancel_not_found(self, client: AsyncClient, user_token):
        resp = await client.post(
            "/api/v1/orders/00000000-0000-0000-0000-000000000000/cancel",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 404
