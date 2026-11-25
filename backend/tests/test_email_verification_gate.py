"""Margen de pedidos antes de exigir el correo confirmado."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.setting_service import set_setting


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, name: str, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "pass1234"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _seed_restaurant(db_session, owner_token: str) -> tuple[Restaurant, MenuItem]:
    owner_id = uuid.UUID(decode_access_token(owner_token)["sub"])
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Negocio Correo",
        owner_id=owner_id,
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Calle Prueba 10",
        is_open=True,
        delivery_radius_m=5000,
        delivery_fee=Decimal("10.00"),
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        name="Pedido de prueba",
        price=Decimal("50.00"),
        preparation_time_min=10,
        is_available=True,
    )
    db_session.add(restaurant)
    db_session.add(item)
    await db_session.commit()
    return restaurant, item


def _payload(restaurant: Restaurant, item: MenuItem) -> dict:
    return {
        "restaurant_id": str(restaurant.id),
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        "delivery_address": "Calle Principal 123",
        "delivery_location": {"lat": 19.44, "lng": -99.14},
    }


def _past_order(
    user_id: uuid.UUID, restaurant_id: uuid.UUID, status: str = "delivered"
) -> Order:
    return Order(
        id=uuid.uuid4(),
        user_id=user_id,
        restaurant_id=restaurant_id,
        status=status,
        subtotal=Decimal("50.00"),
        delivery_fee=Decimal("10.00"),
        total=Decimal("60.00"),
        delivery_address="Calle Principal 123",
        delivery_location="SRID=4326;POINT(-99.14 19.44)",
        payment_method="cash",
        payment_status="approved",
        placed_at=datetime.now(timezone.utc),
    )


async def test_blocks_after_three_orders_without_verification(
    client: AsyncClient, db_session
):
    customer = await _register(client, "Cliente Cortesía", "gate-customer@test.com")
    owner = await _register(client, "Dueño Cortesía", "gate-owner@test.com")
    restaurant, item = await _seed_restaurant(db_session, owner)

    customer_id = uuid.UUID(decode_access_token(customer)["sub"])
    for _ in range(3):
        db_session.add(_past_order(customer_id, restaurant.id))
    await db_session.commit()

    blocked = await client.post(
        "/api/v1/orders", json=_payload(restaurant, item), headers=_headers(customer)
    )
    assert blocked.status_code == 403, blocked.text
    detail = blocked.json()["detail"]
    assert "correo" in detail.lower()
    assert "3" in detail

    user = await db_session.get(User, customer_id)
    user.email_verified = True
    await db_session.commit()

    allowed = await client.post(
        "/api/v1/orders", json=_payload(restaurant, item), headers=_headers(customer)
    )
    assert allowed.status_code == 201, allowed.text


async def test_cancelled_orders_do_not_use_the_grace(
    client: AsyncClient, db_session
):
    customer = await _register(client, "Cliente Canceló", "gate-cancel@test.com")
    owner = await _register(client, "Dueño Canceló", "gate-owner2@test.com")
    restaurant, item = await _seed_restaurant(db_session, owner)

    customer_id = uuid.UUID(decode_access_token(customer)["sub"])
    for _ in range(4):
        db_session.add(_past_order(customer_id, restaurant.id, status="cancelled"))
    await db_session.commit()

    allowed = await client.post(
        "/api/v1/orders", json=_payload(restaurant, item), headers=_headers(customer)
    )
    assert allowed.status_code == 201, allowed.text


async def test_setting_can_require_verification_immediately(
    client: AsyncClient, db_session
):
    customer = await _register(client, "Cliente Estricto", "gate-strict@test.com")
    owner = await _register(client, "Dueño Estricto", "gate-owner3@test.com")
    restaurant, item = await _seed_restaurant(db_session, owner)
    await set_setting(db_session, "REQUIRE_EMAIL_VERIFICATION", "true")
    await db_session.commit()

    blocked = await client.post(
        "/api/v1/orders", json=_payload(restaurant, item), headers=_headers(customer)
    )
    assert blocked.status_code == 403, blocked.text
    assert "correo" in blocked.json()["detail"].lower()
