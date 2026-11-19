"""Tests for delivery endpoints: available, accept, location."""

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.core.constants import OrderStatus


@pytest.fixture
async def user_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Normal User", "email": "normal@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def delivery_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Repartidor Test", "email": "repartidor@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def delivery_person(db_session, delivery_token) -> DeliveryPerson:
    from app.core.security import decode_access_token
    payload = decode_access_token(delivery_token)

    dp = DeliveryPerson(
        user_id=payload["sub"],
        vehicle_type="motorcycle",
        is_available=True,
        rating=4.5,
        total_deliveries=10,
        current_location="SRID=4326;POINT(-99.13 19.43)",
    )
    db_session.add(dp)
    await db_session.commit()
    await db_session.refresh(dp)
    return dp


@pytest.fixture
async def seeded_restaurant(db_session, user_token) -> Restaurant:
    from app.core.security import decode_access_token
    payload = decode_access_token(user_token)

    rid = uuid.uuid4()
    r = Restaurant(
        id=rid, name="Delivery Resto", owner_id=payload["sub"],
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Address 123", is_open=True, rating=4.0,
        delivery_radius_m=5000, delivery_fee=10.00,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(r)
    item = MenuItem(id=uuid.uuid4(), restaurant_id=rid, name="Item", price=30.00,
                    preparation_time_min=5, is_available=True)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(r)
    return r


class TestAvailableDeliveryPersons:
    async def test_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/delivery/available", params={"lat": 19.43, "lng": -99.13})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_with_available(self, client: AsyncClient, delivery_person):
        resp = await client.get("/api/v1/delivery/available", params={"lat": 19.43, "lng": -99.13})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Repartidor Test"

    async def test_unavailable_not_shown(self, client: AsyncClient, db_session, delivery_person):
        delivery_person.is_available = False
        await db_session.commit()

        resp = await client.get("/api/v1/delivery/available", params={"lat": 19.43, "lng": -99.13})
        assert resp.status_code == 200
        assert resp.json() == []


class TestAcceptOrder:
    async def _create_order(self, client, token, resto):
        from app.models.menu_item import MenuItem
        db = None  # We'll fetch the menu item from API instead
        resp = await client.get(f"/api/v1/restaurants/{resto.id}")
        item_id = resp.json()["menu"][0]["id"]

        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": item_id, "quantity": 1}],
                "delivery_address": "Address 123",
                "delivery_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.json()["id"]

    async def test_accept_as_delivery(self, client: AsyncClient, user_token, delivery_token,
                                       delivery_person, seeded_restaurant):
        resto = seeded_restaurant
        order_id = await self._create_order(client, user_token, resto)

        # Set order to ready first (status update)
        resp = await client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "ready"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200

        resp = await client.post(
            f"/api/v1/delivery/accept/{order_id}",
            headers={"Authorization": f"Bearer {delivery_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"

    async def test_accept_keeps_restaurant_status(
        self, client: AsyncClient, user_token, delivery_token, delivery_person, seeded_restaurant,
    ):
        order_id = await self._create_order(client, user_token, seeded_restaurant)
        resp = await client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "preparing"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        accepted = await client.post(
            f"/api/v1/delivery/accept/{order_id}",
            headers={"Authorization": f"Bearer {delivery_token}"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "preparing"

    async def test_pickup_after_ready(
        self, client: AsyncClient, user_token, delivery_token, delivery_person, seeded_restaurant,
    ):
        order_id = await self._create_order(client, user_token, seeded_restaurant)
        await client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "ready"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        accepted = await client.post(
            f"/api/v1/delivery/accept/{order_id}",
            headers={"Authorization": f"Bearer {delivery_token}"},
        )
        assert accepted.status_code == 200
        pickup = await client.post(
            f"/api/v1/delivery/pickup/{order_id}",
            headers={"Authorization": f"Bearer {delivery_token}"},
        )
        assert pickup.status_code == 200
        assert pickup.json()["status"] == "picked_up"

    async def test_pickup_blocked_while_preparing(
        self, client: AsyncClient, user_token, delivery_token, delivery_person, seeded_restaurant,
    ):
        order_id = await self._create_order(client, user_token, seeded_restaurant)
        await client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "preparing"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        accepted = await client.post(
            f"/api/v1/delivery/accept/{order_id}",
            headers={"Authorization": f"Bearer {delivery_token}"},
        )
        assert accepted.status_code == 200
        pickup = await client.post(
            f"/api/v1/delivery/pickup/{order_id}",
            headers={"Authorization": f"Bearer {delivery_token}"},
        )
        assert pickup.status_code == 400

    async def test_accept_as_normal_user(self, client: AsyncClient, user_token, seeded_restaurant):
        resto = seeded_restaurant
        order_id = await self._create_order(client, user_token, resto)

        resp = await client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "ready"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200

        resp = await client.post(
            f"/api/v1/delivery/accept/{order_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


class TestAvailableOrders:
    async def test_includes_distance_and_eta(
        self, client: AsyncClient, db_session, user_token, delivery_token,
        delivery_person, seeded_restaurant,
    ):
        from app.core.security import decode_access_token
        from app.models.order import Order

        payload = decode_access_token(user_token)
        db_session.add(Order(
            user_id=payload["sub"],
            restaurant_id=seeded_restaurant.id,
            status="ready",
            subtotal=100,
            delivery_fee=20,
            total=125,
            delivery_address="Address 123",
            delivery_location="SRID=4326;POINT(-99.13 19.43)",
            delivery_earnings=20,
        ))
        await db_session.commit()

        resp = await client.get(
            "/api/v1/delivery/available-orders",
            params={"lat": 19.43, "lng": -99.13},
            headers={"Authorization": f"Bearer {delivery_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["restaurant_name"] == "Delivery Resto"
        assert data[0]["distance_km"] is not None
        assert data[0]["eta_min"] >= 1

    async def test_requires_delivery_person(
        self, client: AsyncClient, user_token,
    ):
        resp = await client.get(
            "/api/v1/delivery/available-orders",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


class TestPayouts:
    async def test_request_payout_cannot_duplicate_pending(
        self, client: AsyncClient, db_session, user_token, delivery_token,
        delivery_person, seeded_restaurant,
    ):
        from app.core.security import decode_access_token
        from app.models.order import Order
        from app.services.payout_service import credit_courier_for_order

        payload = decode_access_token(user_token)
        order = Order(
            user_id=payload["sub"],
            restaurant_id=seeded_restaurant.id,
            delivery_person_id=delivery_person.id,
            status="delivered",
            subtotal=100,
            delivery_fee=20,
            total=125,
            delivery_address="Address 123",
            delivery_location="SRID=4326;POINT(-99.13 19.43)",
            delivery_earnings=50,
            payment_method="transfer",
            payment_status="approved",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)
        await credit_courier_for_order(db_session, order)
        await db_session.commit()

        headers = {"Authorization": f"Bearer {delivery_token}"}
        first = await client.post("/api/v1/delivery/request-payout", headers=headers)
        assert first.status_code == 200
        assert float(first.json()["total_earnings"]) == 50.0

        # The pending payout already covers the earnings, so a second request
        # must not create another one.
        second = await client.post("/api/v1/delivery/request-payout", headers=headers)
        assert second.status_code == 400

        payouts = await client.get("/api/v1/delivery/payouts", headers=headers)
        assert len(payouts.json()) == 1

    async def test_cash_debt_is_cleared_after_payout(
        self, client: AsyncClient, db_session, user_token, delivery_token,
        delivery_person, seeded_restaurant,
    ):
        from decimal import Decimal
        from app.core.security import decode_access_token
        from app.models.order import Order
        from app.services.payout_service import credit_courier_for_order

        payload = decode_access_token(user_token)
        delivery_person.pending_platform_debt = Decimal("20")
        order = Order(
            user_id=payload["sub"],
            restaurant_id=seeded_restaurant.id,
            delivery_person_id=delivery_person.id,
            status="delivered",
            subtotal=100,
            delivery_fee=20,
            total=125,
            delivery_address="Address 123",
            delivery_location="SRID=4326;POINT(-99.13 19.43)",
            delivery_earnings=50,
            payment_method="transfer",
            payment_status="approved",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)
        await credit_courier_for_order(db_session, order)
        await db_session.commit()

        headers = {"Authorization": f"Bearer {delivery_token}"}
        first = await client.post("/api/v1/delivery/request-payout", headers=headers)
        assert first.status_code == 200, first.text
        assert float(first.json()["total_earnings"]) == 50.0
        assert float(first.json()["net_amount"]) == 30.0

        await db_session.refresh(delivery_person)
        assert float(delivery_person.pending_platform_debt) == 0.0

        second_order = Order(
            user_id=payload["sub"],
            restaurant_id=seeded_restaurant.id,
            delivery_person_id=delivery_person.id,
            status="delivered",
            subtotal=100,
            delivery_fee=20,
            total=100,
            delivery_address="Address 123",
            delivery_location="SRID=4326;POINT(-99.13 19.43)",
            delivery_earnings=40,
            payment_method="transfer",
            payment_status="approved",
        )
        db_session.add(second_order)
        await db_session.commit()
        await db_session.refresh(second_order)
        await credit_courier_for_order(db_session, second_order)
        await db_session.commit()

        second = await client.post("/api/v1/delivery/request-payout", headers=headers)
        assert second.status_code == 200, second.text
        assert float(second.json()["total_earnings"]) == 40.0

    async def test_negative_cut_is_paid_to_platform(
        self, client: AsyncClient, db_session, user_token, delivery_token,
        delivery_person, seeded_restaurant,
    ):
        from decimal import Decimal

        delivery_person.pending_platform_credit = Decimal("20")
        delivery_person.pending_platform_debt = Decimal("50")
        await db_session.commit()

        headers = {"Authorization": f"Bearer {delivery_token}"}
        resp = await client.post("/api/v1/delivery/request-payout", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["direction"] == "to_platform"
        assert float(data["net_amount"]) == -30.0
        assert float(data["total_earnings"]) == 20.0

        await db_session.refresh(delivery_person)
        assert float(delivery_person.pending_platform_debt) == 0.0
        assert float(delivery_person.pending_platform_credit) == 0.0

        again = await client.post("/api/v1/delivery/request-payout", headers=headers)
        assert again.status_code == 400


class TestUpdateLocation:
    async def test_update_as_delivery(self, client: AsyncClient, delivery_token, delivery_person):
        resp = await client.patch(
            "/api/v1/delivery/location",
            json={"lat": 19.44, "lng": -99.14, "speed_kmh": 25.0},
            headers={"Authorization": f"Bearer {delivery_token}"},
        )
        assert resp.status_code == 204

    async def test_update_as_normal_user(self, client: AsyncClient, user_token):
        resp = await client.patch(
            "/api/v1/delivery/location",
            json={"lat": 19.44, "lng": -99.14},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403

    async def test_update_unauthorized(self, client: AsyncClient):
        resp = await client.patch(
            "/api/v1/delivery/location",
            json={"lat": 19.44, "lng": -99.14},
        )
        assert resp.status_code == 401
