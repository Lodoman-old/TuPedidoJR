"""Operación sin repartidores: retención, avisos, admin y cierre."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_schedule import RestaurantSchedule
from app.models.user import User
from app.services.delivery_ops_service import process_delivery_ops
from app.services.setting_service import set_setting


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, name: str, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "pass1234"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["access_token"]


@pytest.fixture
async def owner_token(client: AsyncClient):
    return await _register(client, "Owner Ops", "owner-ops@test.com")


@pytest.fixture
async def customer_token(client: AsyncClient):
    return await _register(client, "Cliente Ops", "customer-ops@test.com")


@pytest.fixture
async def courier_token(client: AsyncClient):
    return await _register(client, "Repartidor Ops", "courier-ops@test.com")


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session, customer_token):
    user = await db_session.get(
        User, uuid.UUID(decode_access_token(customer_token)["sub"])
    )
    user.is_superuser = True
    await db_session.commit()
    return customer_token


@pytest.fixture
async def restaurant(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    rid = uuid.uuid4()
    row = Restaurant(
        id=rid,
        name="Resto Ops",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle Ops 1",
        is_open=True,
        pickup_enabled=True,
        rating=4.5,
        delivery_radius_m=20000,
        delivery_fee=25.00,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=rid,
        name="Platillo Ops",
        price=50.00,
        preparation_time_min=5,
        is_available=True,
    )
    db_session.add(row)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(row)
    await db_session.refresh(item)
    return row, item


@pytest.fixture
async def courier(db_session, courier_token):
    dp = DeliveryPerson(
        user_id=decode_access_token(courier_token)["sub"],
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


async def _enable_ops(db_session):
    await set_setting(db_session, "DELIVERY_OPS_V2_ENABLED", "true")
    await set_setting(db_session, "DELIVERY_MAX_KM", "50")
    await set_setting(db_session, "DELIVERY_APPROVAL_KM", "999")
    await set_setting(db_session, "NEAR_CLOSING_MIN", "0")


def _order_body(restaurant, item, **extra):
    body = {
        "restaurant_id": str(restaurant.id),
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        "delivery_address": "Calle Ops 123",
        "delivery_location": {"lat": 20.645, "lng": -100.99},
        "payment_method": "cash",
    }
    body.update(extra)
    return body


async def _estimate(client, token, restaurant, item, **extra):
    return await client.post(
        "/api/v1/orders/estimate-price",
        json=_order_body(restaurant, item, **extra),
        headers=_headers(token),
    )


async def test_estimate_reports_no_courier(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_ops(db_session)
    row, item = restaurant
    resp = await _estimate(client, customer_token, row, item)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["no_courier"] is True
    assert data["available_couriers"] == 0
    assert data["no_courier_wait_min"] == 30


async def test_delivery_without_courier_requires_choice(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_ops(db_session)
    row, item = restaurant
    resp = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item),
        headers=_headers(customer_token),
    )
    assert resp.status_code == 409, resp.text
    assert "repartidores" in resp.json()["detail"].lower()


async def test_wait_creates_held_order_and_hides_it_from_restaurant(
    client: AsyncClient, db_session, customer_token, owner_token, restaurant
):
    await _enable_ops(db_session)
    row, item = restaurant
    resp = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, no_courier_action="wait"),
        headers=_headers(customer_token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["no_courier_hold"] is True
    assert data["requires_courier_approval"] is True
    assert data["status"] == "awaiting_courier"
    assert data["courier_approval_deadline"] is not None

    listed = await client.get(
        f"/api/v1/restaurants/{row.id}/orders", headers=_headers(owner_token)
    )
    assert listed.status_code == 200
    assert all(order["id"] != data["id"] for order in listed.json())


async def test_pickup_choice_creates_normal_pickup_order(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_ops(db_session)
    row, item = restaurant
    resp = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, fulfillment_type="pickup"),
        headers=_headers(customer_token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["no_courier_hold"] is False
    assert data["fulfillment_type"] == "pickup"
    assert data["delivery_fee"] == "0.00"


async def test_courier_accepts_held_order(
    client: AsyncClient,
    db_session,
    customer_token,
    owner_token,
    courier_token,
    restaurant,
):
    await _enable_ops(db_session)
    row, item = restaurant
    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, no_courier_action="wait"),
        headers=_headers(customer_token),
    )
    order_id = created.json()["id"]

    courier = DeliveryPerson(
        user_id=decode_access_token(courier_token)["sub"],
        vehicle_type="motorcycle",
        is_available=True,
        current_location="SRID=4326;POINT(-100.99 20.64)",
    )
    db_session.add(courier)
    await db_session.commit()
    await db_session.refresh(courier)

    accepted = await client.post(
        f"/api/v1/delivery/accept/{order_id}", headers=_headers(courier_token)
    )
    assert accepted.status_code == 200, accepted.text
    data = accepted.json()
    assert data["status"] == "preparing"
    assert data["no_courier_hold"] is False
    assert data["delivery_person_id"] == str(courier.id)

    visible = await client.get(
        f"/api/v1/restaurants/{row.id}/orders", headers=_headers(owner_token)
    )
    assert any(order["id"] == order_id for order in visible.json())


async def test_delivery_ops_notifies_and_cancels_after_wait(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_ops(db_session)
    row, item = restaurant
    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, no_courier_action="wait"),
        headers=_headers(customer_token),
    )
    order_id = uuid.UUID(created.json()["id"])
    order = await db_session.get(Order, order_id)
    order.courier_approval_deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    first = await process_delivery_ops(db_session)
    assert first["enabled"] is True
    await db_session.refresh(order)
    assert order.no_courier_notified_at is not None
    assert order.no_courier_decision_deadline is not None
    assert order.status == "awaiting_courier"

    order.no_courier_decision_deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    second = await process_delivery_ops(db_session)
    assert second["cancelled"] >= 1
    await db_session.refresh(order)
    assert order.status == "cancelled"


async def test_admin_can_assign_courier(
    client: AsyncClient,
    db_session,
    customer_token,
    superuser_token,
    restaurant,
    courier,
):
    await _enable_ops(db_session)
    row, item = restaurant
    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, no_courier_action="wait"),
        headers=_headers(customer_token),
    )
    order_id = created.json()["id"]

    resp = await client.post(
        f"/api/v1/admin/orders/{order_id}/assign-courier",
        json={"courier_id": str(courier.id)},
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["delivery_person_id"] == str(courier.id)
    assert data["status"] == "preparing"


async def test_admin_can_take_and_deliver_order(
    client: AsyncClient,
    db_session,
    customer_token,
    superuser_token,
    restaurant,
):
    await _enable_ops(db_session)
    row, item = restaurant
    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, no_courier_action="wait"),
        headers=_headers(customer_token),
    )
    order_id = created.json()["id"]

    taken = await client.post(
        f"/api/v1/admin/orders/{order_id}/take-delivery",
        headers=_headers(superuser_token),
    )
    assert taken.status_code == 200, taken.text
    assert taken.json()["admin_delivery"] is True
    assert float(taken.json()["delivery_earnings"]) == 0

    picked = await client.post(
        f"/api/v1/admin/orders/{order_id}/status",
        json={"status": "picked_up"},
        headers=_headers(superuser_token),
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["status"] == "in_delivery"

    delivered = await client.post(
        f"/api/v1/admin/orders/{order_id}/status",
        json={"status": "delivered"},
        headers=_headers(superuser_token),
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "delivered"
    assert delivered.json()["payment_status"] == "approved"


async def test_customer_can_switch_held_order_to_pickup(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_ops(db_session)
    row, item = restaurant
    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, no_courier_action="wait"),
        headers=_headers(customer_token),
    )
    data = created.json()
    original_fee = float(data["delivery_fee"])
    assert original_fee > 0

    resp = await client.post(
        f"/api/v1/orders/{data['id']}/switch-to-pickup",
        headers=_headers(customer_token),
    )
    assert resp.status_code == 200, resp.text
    changed = resp.json()
    assert changed["fulfillment_type"] == "pickup"
    assert float(changed["delivery_fee"]) == 0
    assert float(changed["total"]) == float(data["total"]) - original_fee
    assert changed["no_courier_hold"] is False


async def test_switch_paid_transfer_to_pickup_creates_refund(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_ops(db_session)
    await set_setting(db_session, "TRANSFER_ENABLED", "true")
    row, item = restaurant
    created = await client.post(
        "/api/v1/orders",
        json=_order_body(
            row,
            item,
            payment_method="transfer",
            no_courier_action="wait",
            refund_account_holder="Ana Pérez",
            refund_bank="BBVA",
            refund_clabe="012345678901234567",
        ),
        headers=_headers(customer_token),
    )
    assert created.status_code == 201, created.text
    data = created.json()
    order = await db_session.get(Order, uuid.UUID(data["id"]))
    order.payment_status = "approved"
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{data['id']}/switch-to-pickup",
        headers=_headers(customer_token),
    )
    assert resp.status_code == 200, resp.text
    await db_session.refresh(order)
    assert order.refund_status == "pending"
    assert float(order.refund_amount) == float(data["delivery_fee"])


async def test_near_closing_requires_business_acceptance(
    client: AsyncClient, db_session, customer_token, owner_token, restaurant
):
    await _enable_ops(db_session)
    await set_setting(db_session, "NEAR_CLOSING_MIN", "10000")
    row, item = restaurant
    local_now = datetime.now(ZoneInfo("America/Mexico_City"))
    db_session.add(
        RestaurantSchedule(
            restaurant_id=row.id,
            day_of_week=local_now.weekday(),
            open_time=time(0, 0),
            close_time=time(23, 59),
            is_closed=False,
        )
    )
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, no_courier_action="wait"),
        headers=_headers(customer_token),
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["near_closing"] is True
    assert data["business_confirmation_deadline"] is not None

    listed = await client.get(
        f"/api/v1/restaurants/{row.id}/orders", headers=_headers(owner_token)
    )
    assert any(order["id"] == data["id"] for order in listed.json())

    accepted = await client.patch(
        f"/api/v1/restaurants/{row.id}/orders/{data['id']}/status",
        json={"status": "confirmed"},
        headers=_headers(owner_token),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["near_closing"] is False


async def test_near_closing_timeout_cancels(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_ops(db_session)
    await set_setting(db_session, "NEAR_CLOSING_MIN", "10000")
    row, item = restaurant
    db_session.add(
        RestaurantSchedule(
            restaurant_id=row.id,
            day_of_week=datetime.now(ZoneInfo("America/Mexico_City")).weekday(),
            open_time=time(0, 0),
            close_time=time(23, 59),
            is_closed=False,
        )
    )
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, no_courier_action="wait"),
        headers=_headers(customer_token),
    )
    data = created.json()
    order = await db_session.get(Order, uuid.UUID(data["id"]))
    order.business_confirmation_deadline = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    await db_session.commit()

    result = await process_delivery_ops(db_session)
    assert result["near_closing"] >= 1
    await db_session.refresh(order)
    assert order.status == "cancelled"
    assert "cierre" in (order.cancellation_reason or "").lower()


async def test_own_delivery_is_not_affected(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_ops(db_session)
    row, item = restaurant
    row.delivery_mode = "own"
    await db_session.commit()

    est = await _estimate(client, customer_token, row, item)
    assert est.status_code == 200
    assert est.json()["no_courier"] is False

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item),
        headers=_headers(customer_token),
    )
    assert created.status_code == 201, created.text
    assert created.json()["no_courier_hold"] is False
