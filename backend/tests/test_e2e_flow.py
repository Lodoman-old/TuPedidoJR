"""End-to-end role flow: business, customer, courier and admin.

Covers the real order path with a coupon:
- the business creates the coupon,
- the customer validates it and places the order,
- the business marks the order as ready,
- the courier accepts, picks up and delivers,
- the courier debt and earnings are recorded,
- the courier sends an SOS alert that the admin can see.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import decode_access_token
from app.models.courier_sos import CourierSOS
from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def tokens(client: AsyncClient) -> dict[str, str]:
    roles = {
        "client": ("Cliente E2E", "cliente-e2e@test.com", "4121234567"),
        "owner": ("Negocio E2E", "negocio-e2e@test.com", "4120000001"),
        "courier": ("Repartidor E2E", "repartidor-e2e@test.com", "4120000002"),
        "admin": ("Admin E2E", "admin-e2e@test.com", "4120000003"),
    }
    result = {}
    for role, (name, email, phone) in roles.items():
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "name": name,
                "email": email,
                "phone": phone,
                "password": "pass123",
            },
        )
        assert resp.status_code in (200, 201), resp.text
        result[role] = resp.json()["access_token"]
    return result


@pytest.fixture
async def admin_token(client: AsyncClient, tokens, db_session) -> str:
    token = tokens["admin"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


@pytest.fixture
async def restaurant(db_session, tokens):
    owner_id = uuid.UUID(decode_access_token(tokens["owner"])["sub"])
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Negocio E2E",
        slug=f"negocio-e2e-{uuid.uuid4().hex[:8]}",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 5 de Mayo 100",
        is_open=True,
        status="active",
        delivery_mode="platform",
        delivery_enabled=True,
        pickup_enabled=True,
        delivery_radius_m=5000,
        delivery_fee=Decimal("15.00"),
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        name="Producto E2E",
        price=Decimal("50.00"),
        preparation_time_min=5,
        is_available=True,
    )
    db_session.add_all([resto, item])
    await db_session.commit()
    await db_session.refresh(resto)
    await db_session.refresh(item)
    return resto, item


@pytest.fixture
async def courier(db_session, tokens):
    dp = DeliveryPerson(
        user_id=uuid.UUID(decode_access_token(tokens["courier"])["sub"]),
        vehicle_type="motorcycle",
        is_available=True,
        rating=Decimal("4.8"),
        total_deliveries=0,
        current_location="SRID=4326;POINT(-100.99 20.64)",
    )
    db_session.add(dp)
    await db_session.commit()
    await db_session.refresh(dp)
    return dp


@pytest.mark.asyncio
async def test_full_delivery_flow_with_coupon_and_sos(
    client: AsyncClient, tokens, admin_token, restaurant, courier, db_session
):
    resto, item = restaurant
    owner = _headers(tokens["owner"])
    customer = _headers(tokens["client"])
    courier_h = _headers(tokens["courier"])
    admin_h = _headers(admin_token)
    courier_id = courier.id

    # 1. The business creates a 10% coupon.
    coupon = await client.post(
        f"/api/v1/restaurants/{resto.id}/coupons",
        headers=owner,
        json={
            "code": "E2E10",
            "description": "10% en el flujo E2E",
            "discount_type": "percentage",
            "discount_value": 10,
            "min_order_amount": 50,
            "max_discount": 50,
            "max_uses": 5,
            "is_active": True,
        },
    )
    assert coupon.status_code == 201, coupon.text

    # 2. The customer validates the coupon before buying.
    validation = await client.post(
        "/api/v1/coupons/validate",
        headers=customer,
        json={"code": "E2E10", "subtotal": 100, "restaurant_id": str(resto.id)},
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["valid"] is True
    assert Decimal(validation.json()["discount_amount"]) == Decimal("10")

    # 3. The customer places the order with the coupon and cash payment.
    created = await client.post(
        "/api/v1/orders",
        headers=customer,
        json={
            "restaurant_id": str(resto.id),
            "items": [{"menu_item_id": str(item.id), "quantity": 2}],
            "delivery_address": "Calle 5 de Mayo 100",
            "delivery_location": {"lat": 20.64, "lng": -100.99},
            "coupon_code": "E2E10",
            "payment_method": "cash",
        },
    )
    assert created.status_code == 201, created.text
    order = created.json()
    order_id = order["id"]

    # Transparent breakdown shown to the customer.
    assert order["status"] == "pending"
    assert Decimal(order["subtotal"]) == Decimal("100")
    assert Decimal(order["discount_amount"]) == Decimal("10")
    assert Decimal(order["delivery_fee"]) == Decimal("25")
    assert Decimal(order["platform_commission"]) == Decimal("5")
    assert Decimal(order["flat_usage_fee"]) == Decimal("5")
    assert Decimal(order["total"]) == Decimal("120")
    assert Decimal(order["delivery_earnings"]) == Decimal("25")

    # 4. The business marks the order as ready.
    ready = await client.patch(
        f"/api/v1/orders/{order_id}/status",
        headers=owner,
        json={"status": "ready"},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"

    # The business sees the customer phone to coordinate the order.
    business_orders = await client.get(
        f"/api/v1/restaurants/{resto.id}/orders", headers=owner
    )
    assert business_orders.status_code == 200, business_orders.text
    business_row = next(
        row for row in business_orders.json() if row["id"] == order_id
    )
    assert business_row["customer_phone"] == "4121234567"

    # Unassigned orders must not expose the phone.
    available = await client.get(
        "/api/v1/delivery/available-orders", headers=courier_h
    )
    assert available.status_code == 200, available.text
    available_row = next(
        row for row in available.json() if row["id"] == order_id
    )
    assert available_row["customer_phone"] is None

    # 5. The courier accepts, reports location, picks up and delivers.
    accepted = await client.post(
        f"/api/v1/delivery/accept/{order_id}", headers=courier_h
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["delivery_person_id"] == str(courier_id)

    # The assigned courier sees the phone.
    mine = await client.get("/api/v1/delivery/orders", headers=courier_h)
    assert mine.status_code == 200, mine.text
    mine_row = next(row for row in mine.json() if row["id"] == order_id)
    assert mine_row["customer_phone"] == "4121234567"

    located = await client.patch(
        "/api/v1/delivery/location",
        headers=courier_h,
        json={"lat": 20.6405, "lng": -100.9905},
    )
    assert located.status_code in (200, 204), located.text

    picked = await client.post(
        f"/api/v1/delivery/pickup/{order_id}", headers=courier_h
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["status"] == "picked_up"

    delivered = await client.post(
        f"/api/v1/delivery/deliver/{order_id}", headers=courier_h
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "delivered"

    # 6. Database effects: delivery, debt and earnings.
    db_session.expire_all()
    db_order = await db_session.get(Order, uuid.UUID(order_id))
    assert db_order.status == "delivered"
    assert db_order.delivered_at is not None

    dp = await db_session.get(DeliveryPerson, courier_id)
    assert dp.total_deliveries == 1
    assert dp.current_order_id is None
    # Cash: the courier collected 120 and earned 25, so owes 95.
    assert dp.pending_platform_debt == Decimal("95")

    # 7. The admin sees the order and the courier in the payouts panel.
    payouts = await client.get("/api/v1/admin/payouts", headers=admin_h)
    assert payouts.status_code == 200, payouts.text
    assert "couriers" in payouts.json()

    # 8. Courier SOS: recorded for the security panel.
    sos = await client.post(
        "/api/v1/delivery/sos",
        headers=courier_h,
        json={
            "order_id": order_id,
            "lat": 20.6405,
            "lng": -100.9905,
            "message": "Prueba automática E2E",
        },
    )
    assert sos.status_code in (200, 201), sos.text

    alerts = (await db_session.execute(select(CourierSOS))).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].order_id == uuid.UUID(order_id)
    assert alerts[0].message == "Prueba automática E2E"
