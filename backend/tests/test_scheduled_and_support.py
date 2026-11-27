"""Pedidos programados y apoyo de reparto de TuPedidoJR."""
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

TZ = ZoneInfo("America/Mexico_City")


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
    return await _register(client, "Owner Programado", "owner-sched@test.com")


@pytest.fixture
async def customer_token(client: AsyncClient):
    return await _register(client, "Cliente Programado", "customer-sched@test.com")


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
        name="Resto Programado",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle Programada 1",
        is_open=True,
        pickup_enabled=True,
        business_type="restaurant",
        rating=4.5,
        delivery_radius_m=20000,
        delivery_fee=25.00,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=rid,
        name="Platillo Programado",
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


async def _enable_scheduled(db_session, *, prep_window: int = 60):
    await set_setting(db_session, "DELIVERY_OPS_V2_ENABLED", "true")
    await set_setting(db_session, "DELIVERY_MAX_KM", "50")
    await set_setting(db_session, "DELIVERY_APPROVAL_KM", "999")
    await set_setting(db_session, "SCHEDULED_PREP_WINDOW_MIN", str(prep_window))
    await set_setting(db_session, "SCHEDULED_REMINDER_MIN", "60")
    await set_setting(db_session, "SCHEDULED_APPROVAL_MIN", "30")


def _order_body(restaurant, item, scheduled_for, **extra):
    body = {
        "restaurant_id": str(restaurant.id),
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        "delivery_address": "Calle Programada 123",
        "delivery_location": {"lat": 20.645, "lng": -100.99},
        "payment_method": "cash",
        "scheduled_for": scheduled_for.isoformat(),
    }
    body.update(extra)
    return body


def _add_schedule(db_session, restaurant, day_of_week, open_time, close_time):
    db_session.add(
        RestaurantSchedule(
            restaurant_id=restaurant.id,
            day_of_week=day_of_week,
            open_time=open_time,
            close_time=close_time,
            is_closed=False,
        )
    )


async def test_scheduled_within_hours_no_approval(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_scheduled(db_session)
    row, item = restaurant
    scheduled = datetime.now(TZ) + timedelta(hours=2)
    _add_schedule(db_session, row, scheduled.weekday(), time(0, 0), time(0, 0))
    await db_session.commit()

    resp = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, scheduled),
        headers=_headers(customer_token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["scheduled_outside_hours"] is False
    assert data["scheduled_approval_status"] is None


async def test_scheduled_outside_hours_requires_business_approval(
    client: AsyncClient, db_session, customer_token, owner_token, restaurant
):
    await _enable_scheduled(db_session)
    row, item = restaurant
    target = (datetime.now(TZ) + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    _add_schedule(
        db_session, row, target.weekday(), time(2, 0), time(3, 0)
    )
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, target),
        headers=_headers(customer_token),
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["scheduled_outside_hours"] is True
    assert data["scheduled_approval_status"] == "pending"
    assert data["scheduled_approval_deadline"] is not None

    listed = await client.get(
        f"/api/v1/restaurants/{row.id}/orders", headers=_headers(owner_token)
    )
    assert any(order["id"] == data["id"] for order in listed.json())

    accepted = await client.post(
        f"/api/v1/restaurants/{row.id}/orders/{data['id']}/scheduled-approval",
        json={"accept": True},
        headers=_headers(owner_token),
    )
    assert accepted.status_code == 200, accepted.text
    accepted_data = accepted.json()
    assert accepted_data["scheduled_approval_status"] == "accepted"
    assert accepted_data["scheduled_approval_deadline"] is None


async def test_scheduled_outside_hours_rejection_cancels(
    client: AsyncClient, db_session, customer_token, owner_token, restaurant
):
    await _enable_scheduled(db_session)
    row, item = restaurant
    target = (datetime.now(TZ) + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    _add_schedule(db_session, row, target.weekday(), time(2, 0), time(3, 0))
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, target),
        headers=_headers(customer_token),
    )
    order_id = created.json()["id"]

    rejected = await client.post(
        f"/api/v1/restaurants/{row.id}/orders/{order_id}/scheduled-approval",
        json={"accept": False},
        headers=_headers(owner_token),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "cancelled"
    assert rejected.json()["scheduled_approval_status"] == "rejected"


async def test_scheduled_reminder_is_sent(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_scheduled(db_session)
    row, item = restaurant
    scheduled = datetime.now(TZ) + timedelta(minutes=30)
    _add_schedule(db_session, row, scheduled.weekday(), time(0, 0), time(0, 0))
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, scheduled),
        headers=_headers(customer_token),
    )
    order = await db_session.get(Order, uuid.UUID(created.json()["id"]))

    result = await process_delivery_ops(db_session)
    assert result["reminders"] >= 1
    await db_session.refresh(order)
    assert order.scheduled_reminder_sent_at is not None


async def test_early_prep_warning_and_acceptance(
    client: AsyncClient, db_session, customer_token, owner_token, restaurant
):
    await _enable_scheduled(db_session, prep_window=60)
    row, item = restaurant
    _add_schedule(db_session, row, datetime.now(TZ).weekday(), time(0, 0), time(0, 0))
    await db_session.commit()

    scheduled = datetime.now(TZ) + timedelta(hours=4)
    _add_schedule(db_session, row, scheduled.weekday(), time(0, 0), time(0, 0))
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, scheduled),
        headers=_headers(customer_token),
    )
    order_id = created.json()["id"]

    blocked = await client.patch(
        f"/api/v1/restaurants/{row.id}/orders/{order_id}/status",
        json={"status": "preparing"},
        headers=_headers(owner_token),
    )
    assert blocked.status_code == 409, blocked.text
    assert "perecederos" in blocked.json()["detail"].lower()

    accepted = await client.patch(
        f"/api/v1/restaurants/{row.id}/orders/{order_id}/status",
        json={"status": "preparing", "accept_early_prep": True},
        headers=_headers(owner_token),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["scheduled_prep_ack"] is True


async def test_store_early_prep_has_no_warning(
    client: AsyncClient, db_session, customer_token, owner_token, restaurant
):
    await _enable_scheduled(db_session, prep_window=60)
    row, item = restaurant
    row.business_type = "store"
    _add_schedule(db_session, row, datetime.now(TZ).weekday(), time(0, 0), time(0, 0))
    await db_session.commit()

    scheduled = datetime.now(TZ) + timedelta(hours=4)
    _add_schedule(db_session, row, scheduled.weekday(), time(0, 0), time(0, 0))
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, scheduled),
        headers=_headers(customer_token),
    )
    order_id = created.json()["id"]

    prepared = await client.patch(
        f"/api/v1/restaurants/{row.id}/orders/{order_id}/status",
        json={"status": "preparing"},
        headers=_headers(owner_token),
    )
    assert prepared.status_code == 200, prepared.text


async def test_scheduled_outside_hours_timeout_cancels(
    client: AsyncClient, db_session, customer_token, restaurant
):
    await _enable_scheduled(db_session)
    row, item = restaurant
    target = (datetime.now(TZ) + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    _add_schedule(db_session, row, target.weekday(), time(2, 0), time(3, 0))
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, target),
        headers=_headers(customer_token),
    )
    order = await db_session.get(Order, uuid.UUID(created.json()["id"]))
    order.scheduled_approval_deadline = datetime.now(timezone.utc) - timedelta(
        minutes=1
    )
    await db_session.commit()

    result = await process_delivery_ops(db_session)
    assert result["scheduled_cancelled"] >= 1
    await db_session.refresh(order)
    assert order.status == "cancelled"
    assert order.scheduled_approval_status == "rejected"


async def test_own_delivery_can_request_courier_support(
    client: AsyncClient,
    db_session,
    customer_token,
    owner_token,
    superuser_token,
    restaurant,
):
    await _enable_scheduled(db_session)
    await set_setting(db_session, "COURIER_SUPPORT_ENABLED", "true")
    await set_setting(db_session, "COURIER_SUPPORT_FEE", "30")
    row, item = restaurant
    row.delivery_mode = "own"
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, datetime.now(TZ) + timedelta(days=1)),
        headers=_headers(customer_token),
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    order_row = await db_session.get(Order, uuid.UUID(order_id))
    before_owes = float(order_row.restaurant_owes_platform or 0)

    support = await client.post(
        f"/api/v1/restaurants/{row.id}/orders/{order_id}/request-courier-support",
        headers=_headers(owner_token),
    )
    assert support.status_code == 200, support.text
    data = support.json()
    assert data["courier_support_requested"] is True
    assert data["delivery_mode"] == "platform"
    assert data["status"] == "awaiting_courier"
    assert float(data["courier_support_fee"]) == 30.0
    assert float(data["delivery_earnings"]) == 30.0

    taken = await client.post(
        f"/api/v1/admin/orders/{order_id}/take-delivery",
        headers=_headers(superuser_token),
    )
    assert taken.status_code == 200, taken.text
    delivered = await client.post(
        f"/api/v1/admin/orders/{order_id}/status",
        json={"status": "delivered"},
        headers=_headers(superuser_token),
    )
    assert delivered.status_code == 200, delivered.text
    order = await db_session.get(Order, uuid.UUID(order_id))
    await db_session.refresh(order)
    assert float(order.restaurant_owes_platform) == before_owes + 30.0


async def test_courier_support_disabled_is_rejected(
    client: AsyncClient, db_session, customer_token, owner_token, restaurant
):
    await _enable_scheduled(db_session)
    await set_setting(db_session, "COURIER_SUPPORT_ENABLED", "false")
    row, item = restaurant
    row.delivery_mode = "own"
    await db_session.commit()

    created = await client.post(
        "/api/v1/orders",
        json=_order_body(row, item, datetime.now(TZ) + timedelta(days=1)),
        headers=_headers(customer_token),
    )
    order_id = created.json()["id"]
    resp = await client.post(
        f"/api/v1/restaurants/{row.id}/orders/{order_id}/request-courier-support",
        headers=_headers(owner_token),
    )
    assert resp.status_code == 400
