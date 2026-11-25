"""Zonas calientes y botón de auxilio del repartidor."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Zonas", "email": "cliente-zonas@test.com", "password": "pass1234",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def courier(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Repartidor Zonas", "email": "repartidor-zonas@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    db_session.add(DeliveryPerson(
        user_id=user_id,
        vehicle_type="motorcycle",
        is_available=True,
    ))
    await db_session.commit()
    return token, user_id


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Zonas", "email": "admin-zonas@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


@pytest.fixture
async def restaurant(db_session, customer_token):
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Zonas Negocio",
        slug="zonas-negocio",
        owner_id=uuid.UUID(decode_access_token(customer_token)["sub"]),
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 5 de Mayo 100",
        is_open=True,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    await db_session.commit()
    return resto


@pytest.mark.asyncio
async def test_courier_sos_and_admin_resolve(
    client: AsyncClient, courier, superuser_token
):
    token, _ = courier
    resp = await client.post(
        "/api/v1/delivery/sos",
        headers=_headers(token),
        json={"lat": 20.64, "lng": -100.99, "message": "Prueba de auxilio"},
    )
    assert resp.status_code == 200, resp.text
    sos_id = resp.json()["sos_id"]

    overview = await client.get(
        "/api/v1/admin/security/overview", headers=_headers(superuser_token)
    )
    assert overview.status_code == 200
    alerts = overview.json()["courier_sos"]
    assert len(alerts) == 1
    assert alerts[0]["id"] == sos_id
    assert alerts[0]["message"] == "Prueba de auxilio"

    resolved = await client.post(
        f"/api/v1/admin/security/sos/{sos_id}/resolve",
        headers=_headers(superuser_token),
    )
    assert resolved.status_code == 200

    overview = await client.get(
        "/api/v1/admin/security/overview", headers=_headers(superuser_token)
    )
    assert overview.json()["courier_sos"] == []


@pytest.mark.asyncio
async def test_hot_zones(
    client: AsyncClient, courier, customer_token, restaurant, db_session
):
    token, user_id = courier
    await db_session.execute(
        text(
            "INSERT INTO colonia_areas (nombre, cp, geom) VALUES ('Centro', '38240', "
            "ST_Multi(ST_MakeEnvelope(-101.0, 20.63, -100.98, 20.66, 4326)))"
        )
    )
    now = datetime.now(timezone.utc)
    db_session.add(Order(
        id=uuid.uuid4(),
        user_id=uuid.UUID(decode_access_token(customer_token)["sub"]),
        restaurant_id=restaurant.id,
        status="delivered",
        subtotal=100,
        delivery_fee=25,
        total=125,
        delivery_address="Calle 1",
        delivery_location="SRID=4326;POINT(-100.99 20.64)",
        payment_method="cash",
        placed_at=now,
        delivered_at=now,
    ))
    await db_session.commit()

    resp = await client.get(
        "/api/v1/delivery/hot-zones?days=7", headers=_headers(token)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["zones"][0]["name"] == "Centro"
    assert data["zones"][0]["orders"] == 1
    assert data["peak_hours"]


@pytest.mark.asyncio
async def test_non_courier_cannot_use_tools(
    client: AsyncClient, customer_token
):
    hot = await client.get(
        "/api/v1/delivery/hot-zones", headers=_headers(customer_token)
    )
    assert hot.status_code == 403
    sos = await client.post(
        "/api/v1/delivery/sos", headers=_headers(customer_token), json={"message": "x"}
    )
    assert sos.status_code == 403
