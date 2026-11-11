"""Tests for restaurants endpoints: list, detail, create menu item."""

import uuid

import pytest
from httpx import AsyncClient

from app.core.constants import OrderStatus
from app.models.delivery_person import DeliveryPerson
from app.models.menu_category import MenuCategory
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.restaurant import Restaurant
from app.models.user import User


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Rest Owner", "email": "owner@rest.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def other_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Other User", "email": "other@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def seeded_restaurant(db_session, owner_token) -> Restaurant:
    """Create a restaurant owned by owner_token user."""
    from app.api.deps import get_current_user
    from app.core.security import decode_access_token

    payload = decode_access_token(owner_token)
    owner_id = payload["sub"]

    rid = uuid.uuid4()
    r = Restaurant(
        id=rid, name="Test Taquería", description="Best tacos",
        owner_id=owner_id,
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Calle Test 123", phone="555-0000",
        is_open=True, rating=4.0,
        delivery_radius_m=5000, delivery_fee=10.00,
    )
    db_session.add(r)
    cid = uuid.uuid4()
    cat = MenuCategory(id=cid, restaurant_id=rid, name="Tacos", sort_order=1)
    db_session.add(cat)
    item = MenuItem(id=uuid.uuid4(), restaurant_id=rid, category_id=cid, name="Taco al Pastor",
                    description="Delicious", price=25.00, preparation_time_min=5, is_available=True)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(r)
    return r


class TestListRestaurants:
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/restaurants")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_with_data(self, client: AsyncClient, db_session, owner_token):
        from app.core.security import decode_access_token
        payload = decode_access_token(owner_token)
        r = Restaurant(
            name="Mi Resto", owner_id=payload["sub"],
            location="SRID=4326;POINT(-99.13 19.43)",
            address="Address", is_open=True, rating=3.5,
            delivery_radius_m=3000, delivery_fee=5.00,
        )
        db_session.add(r)
        await db_session.commit()

        resp = await client.get("/api/v1/restaurants")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Mi Resto"
        assert data[0]["distance_m"] is None

    async def test_list_with_coords(self, client: AsyncClient, db_session, owner_token):
        from app.core.security import decode_access_token
        payload = decode_access_token(owner_token)
        r = Restaurant(
            name="Cerca", owner_id=payload["sub"],
            location="SRID=4326;POINT(-99.13 19.43)",
            address="Address", is_open=True, rating=4.0,
            delivery_radius_m=5000, delivery_fee=10.00,
        )
        db_session.add(r)
        await db_session.commit()

        resp = await client.get("/api/v1/restaurants", params={"lat": 19.43, "lng": -99.13})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["distance_m"] is not None

    async def test_list_with_search(self, client: AsyncClient, db_session, owner_token):
        from app.core.security import decode_access_token
        payload = decode_access_token(owner_token)
        r1 = Restaurant(name="Tacos El Norte", owner_id=payload["sub"],
                        location="SRID=4326;POINT(-99.13 19.43)",
                        address="A", is_open=True, rating=4.0,
                        delivery_radius_m=5000, delivery_fee=10.00)
        r2 = Restaurant(name="Pizza Mia", owner_id=payload["sub"],
                        location="SRID=4326;POINT(-99.13 19.43)",
                        address="B", is_open=True, rating=4.0,
                        delivery_radius_m=5000, delivery_fee=10.00)
        db_session.add_all([r1, r2])
        await db_session.commit()

        resp = await client.get("/api/v1/restaurants", params={"q": "tacos"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "Tacos" in data[0]["name"]


class TestGetRestaurant:
    async def test_get_success(self, client: AsyncClient, seeded_restaurant):
        resp = await client.get(f"/api/v1/restaurants/{seeded_restaurant.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Taquería"
        assert len(data["categories"]) == 1
        assert len(data["menu"]) == 1
        assert data["menu"][0]["name"] == "Taco al Pastor"

    async def test_get_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/restaurants/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestCreateMenuItem:
    async def test_create_as_owner(self, client: AsyncClient, seeded_restaurant, owner_token):
        resp = await client.post(
            f"/api/v1/restaurants/{seeded_restaurant.id}/menu",
            json={"name": "Quesadilla", "price": 30.00, "preparation_time_min": 5},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Quesadilla"
        assert float(data["price"]) == 30.0

    async def test_create_as_non_owner(self, client: AsyncClient, seeded_restaurant, other_token):
        resp = await client.post(
            f"/api/v1/restaurants/{seeded_restaurant.id}/menu",
            json={"name": "Quesadilla", "price": 30.00},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_create_unauthorized(self, client: AsyncClient, seeded_restaurant):
        resp = await client.post(
            f"/api/v1/restaurants/{seeded_restaurant.id}/menu",
            json={"name": "Quesadilla", "price": 30.00},
        )
        assert resp.status_code == 401

    async def test_create_invalid_restaurant(self, client: AsyncClient, owner_token):
        resp = await client.post(
            "/api/v1/restaurants/00000000-0000-0000-0000-000000000000/menu",
            json={"name": "Test", "price": 10.00},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert resp.status_code == 404


class TestRestaurantLocation:
    async def test_update_and_get_location(
        self, client: AsyncClient, seeded_restaurant, owner_token, other_token,
    ):
        rid = seeded_restaurant.id
        headers = {"Authorization": f"Bearer {owner_token}"}
        resp = await client.patch(
            f"/api/v1/restaurants/{rid}/location",
            headers=headers,
            json={"lat": 20.65, "lng": -100.99, "address": "Calle Prueba 123, Centro"},
        )
        assert resp.status_code == 200
        assert resp.json()["lat"] == 20.65
        assert resp.json()["lng"] == -100.99

        got = await client.get(f"/api/v1/restaurants/{rid}/location", headers=headers)
        assert got.status_code == 200
        assert got.json()["address"] == "Calle Prueba 123, Centro"
        assert got.json()["lat"] == 20.65

        forbidden = await client.get(
            f"/api/v1/restaurants/{rid}/location",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert forbidden.status_code == 403


class TestRestaurantPayouts:
    async def test_earnings_and_payout_flow(
        self, client: AsyncClient, db_session, seeded_restaurant, owner_token, other_token,
    ):
        from app.core.security import decode_access_token

        owner_id = decode_access_token(owner_token)["sub"]
        db_session.add(Order(
            user_id=owner_id,
            restaurant_id=seeded_restaurant.id,
            status="delivered",
            subtotal=200,
            delivery_fee=20,
            total=225,
            delivery_address="Calle Test 123",
            delivery_location="SRID=4326;POINT(-99.13 19.43)",
            platform_commission=30,
            flat_usage_fee=5,
            delivery_earnings=20,
            payment_method="cash",
        ))
        await db_session.commit()

        headers = {"Authorization": f"Bearer {owner_token}"}
        rid = seeded_restaurant.id

        resp = await client.get(f"/api/v1/restaurants/{rid}/earnings", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        # Restaurant only absorbs the commission; the flat fee is paid by the customer.
        assert float(data["net_earned"]) == 170.0
        assert float(data["available_for_payout"]) == 170.0
        assert float(data["due_to_platform"]) == 0.0

        first = await client.post(f"/api/v1/restaurants/{rid}/request-payout", headers=headers)
        assert first.status_code == 200
        assert float(first.json()["net_payout"]) == 170.0

        second = await client.post(f"/api/v1/restaurants/{rid}/request-payout", headers=headers)
        assert second.status_code == 400

        payouts = await client.get(f"/api/v1/restaurants/{rid}/payouts", headers=headers)
        assert payouts.status_code == 200
        assert len(payouts.json()) == 1

        forbidden = await client.get(
            f"/api/v1/restaurants/{rid}/payouts",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert forbidden.status_code == 403
