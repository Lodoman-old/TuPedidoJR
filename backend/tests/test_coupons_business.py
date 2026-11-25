"""Cupones creados por el negocio."""
import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.restaurant import Restaurant


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Dueño Cupones", "email": "owner-cupones@test.com", "password": "pass1234",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Cupones", "email": "cliente-cupones@test.com", "password": "pass1234",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def restaurant(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Cupones Negocio",
        slug="cupones-negocio",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 5 de Mayo 100",
        is_open=True,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    await db_session.commit()
    return resto


@pytest.mark.asyncio
async def test_owner_creates_and_lists_coupon(
    client: AsyncClient, owner_token, restaurant
):
    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/coupons",
        headers=_headers(owner_token),
        json={
            "code": "promo10",
            "description": "10% de descuento",
            "discount_type": "percentage",
            "discount_value": 10,
            "min_order_amount": 100,
            "max_discount": 50,
            "max_uses": 10,
            "is_active": True,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["code"] == "PROMO10"
    assert data["restaurant_id"] == str(restaurant.id)

    rows = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/coupons", headers=_headers(owner_token)
    )
    assert rows.status_code == 200
    assert len(rows.json()) == 1
    assert rows.json()[0]["code"] == "PROMO10"


@pytest.mark.asyncio
async def test_coupon_validates_for_its_restaurant(
    client: AsyncClient, owner_token, customer_token, restaurant
):
    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/coupons",
        headers=_headers(owner_token),
        json={
            "code": "PROMO10",
            "discount_type": "percentage",
            "discount_value": 10,
            "min_order_amount": 100,
            "max_discount": 50,
        },
    )
    assert created.status_code == 201, created.text

    ok = await client.post(
        "/api/v1/coupons/validate",
        headers=_headers(customer_token),
        json={
            "code": "PROMO10",
            "subtotal": 200,
            "restaurant_id": str(restaurant.id),
        },
    )
    assert ok.status_code == 200
    assert ok.json()["valid"] is True
    assert float(ok.json()["discount_amount"]) == 20

    small = await client.post(
        "/api/v1/coupons/validate",
        headers=_headers(customer_token),
        json={
            "code": "PROMO10",
            "subtotal": 50,
            "restaurant_id": str(restaurant.id),
        },
    )
    assert small.json()["valid"] is False

    other = await client.post(
        "/api/v1/coupons/validate",
        headers=_headers(customer_token),
        json={
            "code": "PROMO10",
            "subtotal": 200,
            "restaurant_id": str(uuid.uuid4()),
        },
    )
    assert other.json()["valid"] is False


@pytest.mark.asyncio
async def test_other_business_cannot_manage_coupons(
    client: AsyncClient, restaurant
):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Otro Dueño", "email": "otro-cupones@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    denied = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/coupons", headers=_headers(token)
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_owner_updates_and_pauses_coupon(
    client: AsyncClient, owner_token, restaurant
):
    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/coupons",
        headers=_headers(owner_token),
        json={
            "code": "PROMO10",
            "discount_type": "fixed",
            "discount_value": 20,
        },
    )
    coupon_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/coupons/{coupon_id}",
        headers=_headers(owner_token),
        json={"discount_value": 30},
    )
    assert updated.status_code == 200
    assert float(updated.json()["discount_value"]) == 30

    paused = await client.delete(
        f"/api/v1/restaurants/{restaurant.id}/coupons/{coupon_id}",
        headers=_headers(owner_token),
    )
    assert paused.status_code == 204
    rows = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/coupons", headers=_headers(owner_token)
    )
    assert rows.json()[0]["is_active"] is False

@pytest.mark.asyncio
async def test_coupon_discount_reduces_business_balance(
    db_session, restaurant, customer_token
):
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.models.order import Order
    from app.services.payout_service import restaurant_balance

    now = datetime.now(timezone.utc)
    db_session.add(Order(
        id=uuid.uuid4(),
        user_id=uuid.UUID(decode_access_token(customer_token)["sub"]),
        restaurant_id=restaurant.id,
        status="delivered",
        subtotal=Decimal("100.00"),
        discount_amount=Decimal("20.00"),
        platform_commission=Decimal("5.00"),
        flat_usage_fee=Decimal("5.00"),
        delivery_fee=Decimal("25.00"),
        total=Decimal("110.00"),
        delivery_address="Calle 1",
        delivery_location="SRID=4326;POINT(-100.99 20.64)",
        payment_method="transfer",
        payment_status="approved",
        placed_at=now,
        delivered_at=now,
    ))
    await db_session.commit()

    balance = await restaurant_balance(db_session, restaurant.id)
    assert balance["earned"] == Decimal("75.00")
