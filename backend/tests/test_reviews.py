"""Tests for rating the restaurant and the courier separately."""

import uuid

import pytest
from httpx import AsyncClient

from app.core.constants import OrderStatus
from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.restaurant import Restaurant


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Reseñas", "email": "cliente-resenas@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Dueño Reseñas", "email": "dueno-resenas@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def courier(db_session, client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Repartidor Reseñas", "email": "repartidor-resenas@test.com", "password": "pass123",
    })
    payload = decode_access_token(resp.json()["access_token"])
    dp = DeliveryPerson(
        user_id=payload["sub"],
        vehicle_type="motorcycle",
        is_available=True,
        rating=4.5,
        total_deliveries=0,
    )
    db_session.add(dp)
    await db_session.commit()
    await db_session.refresh(dp)
    return dp


@pytest.fixture
async def restaurant(db_session, owner_token):
    payload = decode_access_token(owner_token)
    rid = uuid.uuid4()
    resto = Restaurant(
        id=rid, name="Resto Reseñas", owner_id=payload["sub"],
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 1", is_open=True, rating=4.0,
        delivery_radius_m=5000, delivery_fee=15.00,
    )
    item = MenuItem(
        id=uuid.uuid4(), restaurant_id=rid, name="Platillo",
        price=50.00, preparation_time_min=5, is_available=True,
    )
    db_session.add(resto)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(resto)
    await db_session.refresh(item)
    return resto, item


class TestOrderReviews:
    async def test_restaurant_and_courier_reviews_separately(
        self, client: AsyncClient, db_session, customer_token, restaurant, courier,
    ):
        resto, item = restaurant
        created = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Calle 1",
                "delivery_location": {"lat": 20.6449, "lng": -100.9945},
                "payment_method": "cash",
            },
            headers=_headers(customer_token),
        )
        assert created.status_code == 201, created.text
        order_id = created.json()["id"]

        order = await db_session.get(Order, uuid.UUID(order_id))
        order.status = OrderStatus.DELIVERED
        order.delivery_person_id = courier.id
        await db_session.commit()

        restaurant_review = await client.post(
            "/api/v1/reviews",
            json={
                "order_id": order_id,
                "restaurant_id": str(resto.id),
                "rating": 5,
                "comment": "Excelente comida",
            },
            headers=_headers(customer_token),
        )
        assert restaurant_review.status_code == 201, restaurant_review.text

        courier_review = await client.post(
            "/api/v1/reviews",
            json={
                "order_id": order_id,
                "delivery_person_id": str(courier.id),
                "rating": 4,
                "comment": "Llegó bien",
            },
            headers=_headers(customer_token),
        )
        assert courier_review.status_code == 201, courier_review.text

        duplicate = await client.post(
            "/api/v1/reviews",
            json={
                "order_id": order_id,
                "restaurant_id": str(resto.id),
                "rating": 3,
            },
            headers=_headers(customer_token),
        )
        assert duplicate.status_code == 400

        listed = await client.get(
            f"/api/v1/reviews/order/{order_id}",
            headers=_headers(customer_token),
        )
        assert listed.status_code == 200
        data = listed.json()
        assert len(data) == 2
        assert any(row["restaurant_id"] for row in data)
        assert any(row["delivery_person_id"] for row in data)
