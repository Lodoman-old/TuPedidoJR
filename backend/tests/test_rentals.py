"""Pruebas del módulo de rentas (salones, inflables, sillas)."""

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
        "name": "Dueño Rentas", "email": "owner-rentas@test.com", "password": "pass1234",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Rentas", "email": "cliente-rentas@test.com", "password": "pass1234",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def business(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Rentas Demo",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 5 de Mayo 100",
        business_type="rental",
        appointments_enabled=True,
        catalog_enabled=False,
        is_open=True,
        rating=5.0,
        delivery_radius_m=3000,
        delivery_fee=0,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    await db_session.commit()
    await db_session.refresh(resto)
    return resto


async def _item(client, token, resto, **overrides):
    payload = {
        "name": "Inflable 5 horas",
        "duration_min": 300,
        "price": 500,
        "stock": 2,
        "requires_address": False,
    }
    payload.update(overrides)
    resp = await client.post(
        f"/api/v1/rentals/{resto.id}/items",
        headers=_headers(token),
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_rental_items_and_multi_item_booking(
    client, owner_token, customer_token, business
):
    salon = await _item(client, owner_token, business, name="Salón", duration_min=600, price=1500, stock=1)
    sound = await _item(client, owner_token, business, name="Sonido", duration_min=600, price=800, stock=2)
    target = date.today() + timedelta(days=5)

    booking = await client.post(
        f"/api/v1/rentals/{business.id}/bookings",
        headers=_headers(customer_token),
        json={
            "client_name": "Cliente Rentas",
            "client_phone": "4121234567",
            "items": [
                {"service_id": salon["id"], "quantity": 1, "start_at": f"{target.isoformat()}T16:00:00"},
                {"service_id": sound["id"], "quantity": 1, "start_at": f"{target.isoformat()}T16:00:00"},
            ],
            "payment_mode": "cash",
        },
    )
    assert booking.status_code == 201, booking.text
    data = booking.json()
    assert len(data["items"]) == 2
    assert float(data["cash_due"]) == 2305
    assert float(data["platform_fee"]) == 10
    assert float(data["business_debt"]) == 10
    assert data["address"] is None

    mine = await client.get(
        "/api/v1/rentals/my-bookings", headers=_headers(customer_token)
    )
    assert mine.status_code == 200
    assert any(row["id"] == data["id"] for row in mine.json())


@pytest.mark.asyncio
async def test_rental_stock_blocks_overlap(
    client, owner_token, customer_token, business
):
    item = await _item(client, owner_token, business, name="Sillas", stock=10, duration_min=120, price=10)
    target = date.today() + timedelta(days=4)
    first = await client.post(
        f"/api/v1/rentals/{business.id}/bookings",
        headers=_headers(customer_token),
        json={
            "client_name": "Cliente 1",
            "items": [{"service_id": item["id"], "quantity": 8, "start_at": f"{target.isoformat()}T10:00:00"}],
            "payment_mode": "cash",
        },
    )
    assert first.status_code == 201, first.text

    blocked = await client.post(
        f"/api/v1/rentals/{business.id}/bookings",
        headers=_headers(customer_token),
        json={
            "client_name": "Cliente 2",
            "items": [{"service_id": item["id"], "quantity": 3, "start_at": f"{target.isoformat()}T11:00:00"}],
            "payment_mode": "cash",
        },
    )
    assert blocked.status_code == 409
    assert "no está disponible" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_rental_requires_address_when_delivery(
    client, owner_token, customer_token, business
):
    item = await _item(
        client, owner_token, business, name="Inflable a domicilio",
        duration_min=300, price=600, stock=1, requires_address=True,
    )
    target = date.today() + timedelta(days=6)

    missing = await client.post(
        f"/api/v1/rentals/{business.id}/bookings",
        headers=_headers(customer_token),
        json={
            "client_name": "Cliente",
            "items": [{"service_id": item["id"], "quantity": 1, "start_at": f"{target.isoformat()}T12:00:00"}],
            "payment_mode": "cash",
        },
    )
    assert missing.status_code == 400
    assert "dirección" in missing.json()["detail"].lower()

    ok = await client.post(
        f"/api/v1/rentals/{business.id}/bookings",
        headers=_headers(customer_token),
        json={
            "client_name": "Cliente",
            "items": [{"service_id": item["id"], "quantity": 1, "start_at": f"{target.isoformat()}T12:00:00"}],
            "address": "Calle 5 de Mayo 123",
            "lat": 20.64,
            "lng": -100.99,
            "payment_mode": "cash",
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["address"] == "Calle 5 de Mayo 123"


@pytest.mark.asyncio
async def test_rental_slots_respect_quantity(
    client, owner_token, customer_token, business
):
    item = await _item(client, owner_token, business, name="Manteles", stock=5, duration_min=60, price=20)
    target = date.today() + timedelta(days=3)
    resp = await client.get(
        f"/api/v1/rentals/{business.id}/items/{item['id']}/slots",
        params={"date": target.isoformat(), "quantity": 5},
    )
    assert resp.status_code == 200
    assert "10:00" in resp.json()["slots"]
