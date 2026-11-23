"""Checklist de activación para negocios."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_schedule import RestaurantSchedule


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Dueño Onboarding",
            "email": email,
            "phone": "4121234567",
            "password": "pass123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _restaurant(db_session, token: str) -> Restaurant:
    owner_id = uuid.UUID(decode_access_token(token)["sub"])
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Negocio Onboarding",
        slug=f"onboarding-{uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 1",
        is_open=True,
        status="active",
        public_page_enabled=True,
        delivery_enabled=True,
        pickup_enabled=False,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    await db_session.commit()
    await db_session.refresh(resto)
    return resto


async def test_onboarding_progress_and_next_steps(client, db_session):
    token = await _register(client, "onboarding1@test.com")
    resto = await _restaurant(db_session, token)
    db_session.add(MenuItem(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        name="Producto",
        price=Decimal("50.00"),
        preparation_time_min=5,
        is_available=True,
    ))
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/restaurants/{resto.id}/onboarding", headers=_headers(token)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    items = {row["key"]: row for row in data["items"]}
    assert data["total"] == 5
    assert items["catalog"]["done"] is True
    assert items["delivery"]["done"] is True
    assert items["qr"]["done"] is True
    assert items["profile"]["done"] is False
    assert items["schedule"]["done"] is False
    assert data["completed"] == 3
    assert data["published"] is True
    assert data["next_step"]["key"] in {"profile", "schedule"}

    resto.description = "Comida casera"
    resto.phone = "4121234567"
    resto.logo_url = "/static/uploads/logo.png"
    db_session.add(RestaurantSchedule(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        day_of_week=0,
        open_time=datetime.strptime("09:00", "%H:%M").time(),
        close_time=datetime.strptime("18:00", "%H:%M").time(),
        is_closed=False,
    ))
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/restaurants/{resto.id}/onboarding", headers=_headers(token)
    )
    data = resp.json()
    items = {row["key"]: row for row in data["items"]}
    assert items["profile"]["done"] is True
    assert items["schedule"]["done"] is True
    assert data["completed"] == 5
    assert data["percent"] == 100


async def test_onboarding_forbidden_for_other_user(client, db_session):
    owner = await _register(client, "onboarding-owner@test.com")
    other = await _register(client, "onboarding-other@test.com")
    resto = await _restaurant(db_session, owner)
    resp = await client.get(
        f"/api/v1/restaurants/{resto.id}/onboarding", headers=_headers(other)
    )
    assert resp.status_code == 403
