"""Pedidos lejanos: aprobación del repartidor antes de preparar y reembolsos."""

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.setting import Setting
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, name: str, email: str) -> str:
    resp = await client.post("/api/v1/auth/register", json={
        "name": name, "email": email, "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def owner_token(client: AsyncClient):
    return await _register(client, "Owner Lejano", "owner-far@test.com")


@pytest.fixture
async def customer_token(client: AsyncClient):
    return await _register(client, "Cliente Lejano", "customer-far@test.com")


@pytest.fixture
async def courier_token(client: AsyncClient):
    return await _register(client, "Repartidor Lejano", "courier-far@test.com")


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session, customer_token):
    from app.core.security import decode_access_token
    payload = decode_access_token(customer_token)
    user = await db_session.get(User, uuid.UUID(payload["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return customer_token


@pytest.fixture
async def courier(db_session, courier_token):
    from app.core.security import decode_access_token
    payload = decode_access_token(courier_token)
    dp = DeliveryPerson(
        user_id=payload["sub"],
        vehicle_type="motorcycle",
        is_available=True,
        rating=4.5,
        total_deliveries=0,
        current_location="SRID=4326;POINT(-100.99 20.64)",
    )
    db_session.add(dp)
    await db_session.commit()
    await db_session.refresh(dp)
    return dp


@pytest.fixture
async def seeded_restaurant(db_session, owner_token):
    from app.core.security import decode_access_token
    payload = decode_access_token(owner_token)
    rid = uuid.uuid4()
    restaurant = Restaurant(
        id=rid,
        name="Resto Lejano",
        owner_id=payload["sub"],
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 1",
        is_open=True,
        rating=4.5,
        delivery_radius_m=20000,
        delivery_fee=25.00,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    item = MenuItem(
        id=uuid.uuid4(), restaurant_id=rid, name="Platillo",
        price=50.00, preparation_time_min=5, is_available=True,
    )
    db_session.add(restaurant)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(restaurant)
    await db_session.refresh(item)
    return restaurant, item


async def _create_far_order(
    client: AsyncClient,
    token: str,
    restaurant,
    item,
    payment_method: str = "cash",
    refund_account: dict | None = None,
):
    body = {
        "restaurant_id": str(restaurant.id),
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        "delivery_address": "Calle lejana 123",
        # ~10 km al norte del restaurante.
        "delivery_location": {"lat": 20.73, "lng": -100.99},
        "payment_method": payment_method,
    }
    if refund_account:
        body.update(refund_account)
    return await client.post("/api/v1/orders", json=body, headers=_headers(token))


async def _confirm(client: AsyncClient, token: str, restaurant, order_id: str):
    return await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order_id}/status",
        json={"status": "confirmed"},
        headers=_headers(token),
    )


async def test_far_order_needs_courier_before_preparing(
    client: AsyncClient,
    db_session,
    owner_token,
    customer_token,
    courier_token,
    courier,
    seeded_restaurant,
):
    restaurant, item = seeded_restaurant
    db_session.add(Setting(key="DELIVERY_APPROVAL_KM", value="8"))
    db_session.add(Setting(key="DELIVERY_MAX_KM", value="50"))
    await db_session.commit()

    created = await _create_far_order(client, customer_token, restaurant, item)
    assert created.status_code == 201
    order = created.json()
    assert order["requires_courier_approval"] is True
    assert order["courier_approval_deadline"] is not None

    # Se ofrece a los repartidores desde que se paga, antes de que el
    # restaurante confirme.
    available_before = await client.get(
        "/api/v1/delivery/available-orders", headers=_headers(courier_token)
    )
    assert available_before.status_code == 200
    assert any(row["id"] == order["id"] for row in available_before.json())

    confirmed = await _confirm(client, owner_token, restaurant, order["id"])
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "awaiting_courier"

    # El restaurante no puede preparar hasta que un repartidor acepte.
    early = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order['id']}/status",
        json={"status": "preparing"},
        headers=_headers(owner_token),
    )
    assert early.status_code == 400

    available = await client.get(
        "/api/v1/delivery/available-orders", headers=_headers(courier_token)
    )
    assert available.status_code == 200
    assert any(row["id"] == order["id"] for row in available.json())

    accepted = await client.post(
        f"/api/v1/delivery/accept/{order['id']}", headers=_headers(courier_token)
    )
    assert accepted.status_code == 200
    accepted_order = accepted.json()
    assert accepted_order["status"] == "preparing"
    assert accepted_order["delivery_person_id"] is not None

    ready = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/orders/{order['id']}/status",
        json={"status": "ready"},
        headers=_headers(owner_token),
    )
    assert ready.status_code == 200
    assert ready.json()["status"] == "in_delivery"


async def test_courier_can_accept_before_restaurant_confirmation(
    client: AsyncClient,
    db_session,
    owner_token,
    customer_token,
    courier_token,
    courier,
    seeded_restaurant,
):
    restaurant, item = seeded_restaurant
    db_session.add(Setting(key="DELIVERY_MAX_KM", value="50"))
    await db_session.commit()

    created = await _create_far_order(client, customer_token, restaurant, item)
    assert created.status_code == 201
    order = created.json()

    accepted = await client.post(
        f"/api/v1/delivery/accept/{order['id']}", headers=_headers(courier_token)
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "pending"
    assert accepted.json()["delivery_person_id"] is not None

    confirmed = await _confirm(client, owner_token, restaurant, order["id"])
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "preparing"


async def test_near_order_keeps_normal_flow(
    client: AsyncClient, db_session, owner_token, customer_token, seeded_restaurant
):
    restaurant, item = seeded_restaurant
    created = await client.post(
        "/api/v1/orders",
        json={
            "restaurant_id": str(restaurant.id),
            "items": [{"menu_item_id": str(item.id), "quantity": 1}],
            "delivery_address": "Calle cercana 1",
            "delivery_location": {"lat": 20.645, "lng": -100.99},
            "payment_method": "cash",
        },
        headers=_headers(customer_token),
    )
    assert created.status_code == 201
    order = created.json()
    assert order["requires_courier_approval"] is False

    confirmed = await _confirm(client, owner_token, restaurant, order["id"])
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"


async def test_far_transfer_requires_refund_account(
    client: AsyncClient, db_session, customer_token, seeded_restaurant
):
    restaurant, item = seeded_restaurant
    db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
    db_session.add(Setting(key="DELIVERY_MAX_KM", value="50"))
    await db_session.commit()

    missing = await _create_far_order(
        client, customer_token, restaurant, item, payment_method="transfer"
    )
    assert missing.status_code == 400
    assert "CLABE" in missing.json()["detail"]

    ok = await _create_far_order(
        client, customer_token, restaurant, item,
        payment_method="transfer",
        refund_account={
            "refund_account_holder": "Ana Pérez",
            "refund_bank": "BBVA",
            "refund_clabe": "012345678901234567",
        },
    )
    assert ok.status_code == 201
    data = ok.json()
    assert data["refund_account_holder"] == "Ana Pérez"
    assert data["refund_clabe"] == "012345678901234567"


async def test_expired_far_order_is_cancelled_and_refunded(
    client: AsyncClient,
    db_session,
    owner_token,
    customer_token,
    seeded_restaurant,
):
    from datetime import datetime, timedelta as td, timezone

    from app.models.order import Order
    from app.services.courier_timeout_service import cancel_expired_awaiting_orders

    restaurant, item = seeded_restaurant
    db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
    db_session.add(Setting(key="DELIVERY_MAX_KM", value="50"))
    await db_session.commit()

    created = await _create_far_order(
        client, customer_token, restaurant, item,
        payment_method="transfer",
        refund_account={
            "refund_account_holder": "Ana Pérez",
            "refund_bank": "BBVA",
            "refund_clabe": "012345678901234567",
        },
    )
    assert created.status_code == 201
    order = created.json()
    assert order["courier_approval_deadline"] is not None

    db_order = await db_session.get(Order, uuid.UUID(order["id"]))
    db_order.payment_status = "approved"
    db_order.courier_approval_deadline = datetime.now(timezone.utc) - td(minutes=1)
    await db_session.commit()

    cancelled = await cancel_expired_awaiting_orders(db_session)
    assert cancelled == 1
    await db_session.refresh(db_order)
    assert db_order.status == "cancelled"
    assert db_order.refund_status == "pending"
    assert "repartidor" in (db_order.cancellation_reason or "").lower()


async def test_cancelled_far_transfer_creates_pending_refund(
    client: AsyncClient,
    db_session,
    owner_token,
    customer_token,
    superuser_token,
    seeded_restaurant,
):
    restaurant, item = seeded_restaurant
    db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
    db_session.add(Setting(key="DELIVERY_MAX_KM", value="50"))
    await db_session.commit()

    created = await _create_far_order(
        client, customer_token, restaurant, item,
        payment_method="transfer",
        refund_account={
            "refund_account_holder": "Ana Pérez",
            "refund_bank": "BBVA",
            "refund_clabe": "012345678901234567",
        },
    )
    assert created.status_code == 201
    order = created.json()
    confirmed = await _confirm(client, owner_token, restaurant, order["id"])
    assert confirmed.json()["status"] == "awaiting_courier"

    from app.models.order import Order
    db_order = await db_session.get(Order, uuid.UUID(order["id"]))
    db_order.payment_status = "approved"
    await db_session.commit()

    cancelled = await client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        json={"reason": "Ningún repartidor aceptó"},
        headers=_headers(customer_token),
    )
    assert cancelled.status_code == 200
    data = cancelled.json()
    assert data["status"] == "cancelled"
    assert data["refund_status"] == "pending"
    assert float(data["refund_amount"]) == float(order["total"])

    pending = await client.get(
        "/api/v1/admin/refunds/pending", headers=_headers(superuser_token)
    )
    assert pending.status_code == 200
    row = next(r for r in pending.json() if r["id"] == order["id"])
    assert row["account_holder"] == "Ana Pérez"
    assert row["clabe"] == "012345678901234567"

    marked = await client.post(
        f"/api/v1/admin/refunds/{order['id']}/mark-refunded",
        headers=_headers(superuser_token),
    )
    assert marked.status_code == 200
    assert marked.json()["refund_status"] == "refunded"
