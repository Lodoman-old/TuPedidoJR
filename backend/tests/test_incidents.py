"""Incidencias de entrega: política de certeza."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_incident import DeliveryIncident
from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_adjustment import RestaurantAdjustment
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Incidencias", "email": "inc-customer@test.com", "password": "pass1234",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def admin_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Incidencias", "email": "inc-admin@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


@pytest.fixture
async def courier(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Repartidor Incidencias", "email": "inc-courier@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    dp = DeliveryPerson(
        user_id=decode_access_token(token)["sub"],
        vehicle_type="motorcycle",
        is_available=True,
    )
    db_session.add(dp)
    await db_session.commit()
    await db_session.refresh(dp)
    return token, dp


@pytest.fixture
async def restaurant(db_session, customer_token):
    row = Restaurant(
        id=uuid.uuid4(),
        name="Resto Incidencias",
        owner_id=decode_access_token(customer_token)["sub"],
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Calle 1",
        delivery_mode="platform",
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(row)
    db_session.add(MenuItem(
        id=uuid.uuid4(), restaurant_id=row.id, name="Item", price=100,
        preparation_time_min=5, is_available=True,
    ))
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _order(
    db_session,
    customer_token,
    restaurant,
    courier,
    *,
    subtotal="100",
    total="120",
    earnings="20",
    payment_method="cash",
    payment_status="pending",
):
    order = Order(
        user_id=decode_access_token(customer_token)["sub"],
        restaurant_id=restaurant.id,
        delivery_person_id=courier.id,
        status="in_delivery",
        subtotal=Decimal(subtotal),
        delivery_fee=Decimal(earnings),
        total=Decimal(total),
        delivery_address="Calle 1",
        delivery_location="SRID=4326;POINT(-99.13 19.43)",
        delivery_earnings=Decimal(earnings),
        payment_method=payment_method,
        payment_status=payment_status,
        delivery_mode="platform",
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


async def _incident_for(db_session, entity_id) -> DeliveryIncident:
    from sqlalchemy import select

    result = await db_session.execute(
        select(DeliveryIncident).where(DeliveryIncident.entity_id == entity_id)
    )
    return result.scalars().first()


async def _fail(client, token, order):
    resp = await client.post(
        f"/api/v1/delivery/orders/{order.id}/fail",
        json={
            "reason_code": "customer_unreachable",
            "notes": "No contesta",
            "photo_url": "/static/uploads/evidencia.png",
        },
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestIncidentPolicy:
    async def test_food_cash_discard_charges_business_and_customer(
        self, client, db_session, customer_token, admin_token, courier, restaurant,
    ):
        token, dp = courier
        order = await _order(db_session, customer_token, restaurant, dp)

        data = await _fail(client, token, order)
        assert data["status"] == "delivery_failed"
        incident = await _incident_for(db_session, order.id)
        assert incident is not None
        assert incident.status == "reported"

        limits = await client.get("/api/v1/delivery/limits", headers=_headers(token))
        assert limits.status_code == 200
        assert limits.json()["active"] == 0

        resp = await client.post(
            f"/api/v1/admin/incidents/{incident.id}/discard",
            json={"notes": "Se desechó", "courier_fault": False},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text

        await db_session.refresh(dp)
        assert dp.pending_platform_credit == Decimal("20")
        customer = await db_session.get(User, order.user_id)
        await db_session.refresh(customer)
        assert customer.pending_balance == Decimal("120")

        from sqlalchemy import select
        result = await db_session.execute(
            select(RestaurantAdjustment).where(
                RestaurantAdjustment.incident_id == incident.id
            )
        )
        adjustments = result.scalars().all()
        assert len(adjustments) == 1
        assert adjustments[0].amount == Decimal("100")

    async def test_paid_non_perishable_return_refunds_product_only(
        self, client, db_session, customer_token, admin_token, courier, restaurant,
    ):
        token, dp = courier
        order = await _order(
            db_session, customer_token, restaurant, dp,
            total="130", payment_method="transfer", payment_status="approved",
        )
        await _fail(client, token, order)
        incident = await _incident_for(db_session, order.id)

        resp = await client.post(
            f"/api/v1/admin/incidents/{incident.id}/return",
            json={"notes": "Devuelto al negocio"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text

        await db_session.refresh(order)
        assert order.refund_amount == Decimal("100")
        assert order.refund_status == "pending"
        await db_session.refresh(dp)
        assert dp.pending_platform_credit == Decimal("20")
        customer = await db_session.get(User, order.user_id)
        await db_session.refresh(customer)
        assert customer.pending_balance == Decimal("0")

    async def test_courier_fault_above_limit_requires_authorization(
        self, client, db_session, customer_token, admin_token, courier, restaurant,
    ):
        token, dp = courier
        order = await _order(
            db_session, customer_token, restaurant, dp,
            subtotal="600", total="620",
        )
        await _fail(client, token, order)
        incident = await _incident_for(db_session, order.id)

        resp = await client.post(
            f"/api/v1/admin/incidents/{incident.id}/discard",
            json={"notes": "Dañado por el repartidor", "courier_fault": True},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text
        await db_session.refresh(incident)
        assert incident.status == "authorization"
        assert incident.courier_pay == Decimal("0")
        assert incident.business_pay == Decimal("0")

        resp = await client.post(
            f"/api/v1/admin/incidents/{incident.id}/authorize",
            json={"absorb": True, "notes": "La empresa absorbe"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text
        await db_session.refresh(incident)
        assert incident.status == "resolved"
        assert incident.business_pay == Decimal("600")

    async def test_redelivery_adds_configurable_fee(
        self, client, db_session, customer_token, admin_token, courier, restaurant,
    ):
        token, dp = courier
        order = await _order(db_session, customer_token, restaurant, dp)
        await _fail(client, token, order)
        incident = await _incident_for(db_session, order.id)

        resp = await client.post(
            f"/api/v1/admin/incidents/{incident.id}/redeliver",
            json={"fee": 15},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text

        await db_session.refresh(order)
        assert order.status == "awaiting_courier"
        assert order.delivery_person_id is None
        assert order.total == Decimal("135")
        assert order.redelivery_fee == Decimal("15")
        await db_session.refresh(dp)
        assert dp.pending_platform_credit == Decimal("20")
