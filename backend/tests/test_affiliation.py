"""Afiliación anual: visibilidad, panel del admin y recordatorios."""

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.models.restaurant import Restaurant
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Owner Afiliación", "email": "owner-aff@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Afiliación", "email": "admin-aff@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    from app.core.security import decode_access_token
    payload = decode_access_token(token)
    user = await db_session.get(User, uuid.UUID(payload["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


async def _make_restaurant(db_session, owner_token, expires_at):
    from app.core.security import decode_access_token
    payload = decode_access_token(owner_token)
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Resto Afiliación",
        owner_id=payload["sub"],
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 1",
        is_open=True,
        rating=4.5,
        delivery_radius_m=5000,
        delivery_fee=15.00,
        affiliation_expires_at=expires_at,
    )
    db_session.add(restaurant)
    await db_session.commit()
    await db_session.refresh(restaurant)
    return restaurant


async def test_unpaid_restaurant_is_hidden(client: AsyncClient, db_session, owner_token):
    restaurant = await _make_restaurant(db_session, owner_token, None)

    listing = await client.get("/api/v1/restaurants")
    assert listing.status_code == 200
    assert listing.json() == []

    detail = await client.get(f"/api/v1/restaurants/{restaurant.id}")
    assert detail.status_code == 404


async def test_expired_restaurant_is_hidden(client: AsyncClient, db_session, owner_token):
    restaurant = await _make_restaurant(
        db_session, owner_token, date.today() - timedelta(days=1)
    )

    listing = await client.get("/api/v1/restaurants")
    assert listing.status_code == 200
    assert listing.json() == []

    detail = await client.get(f"/api/v1/restaurants/{restaurant.id}")
    assert detail.status_code == 404


async def test_paid_restaurant_is_visible_with_days_left(
    client: AsyncClient, db_session, owner_token
):
    await _make_restaurant(db_session, owner_token, date.today() + timedelta(days=300))

    listing = await client.get("/api/v1/restaurants")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = await client.get(f"/api/v1/restaurants/{listing.json()[0]['id']}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["affiliated"] is True
    assert data["affiliation_days_left"] == 300


async def test_admin_marks_affiliation_paid(
    client: AsyncClient, db_session, owner_token, superuser_token
):
    restaurant = await _make_restaurant(db_session, owner_token, None)

    resp = await client.patch(
        f"/api/v1/admin/affiliations/{restaurant.id}",
        json={"paid": True},
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["affiliated"] is True
    assert data["affiliation_expires_at"] == (date.today() + timedelta(days=365)).isoformat()

    rows = await client.get(
        "/api/v1/admin/affiliations", headers=_headers(superuser_token)
    )
    assert rows.status_code == 200
    assert any(row["id"] == str(restaurant.id) for row in rows.json())

    # Quitar la afiliación la oculta de nuevo.
    removed = await client.patch(
        f"/api/v1/admin/affiliations/{restaurant.id}",
        json={"paid": False},
        headers=_headers(superuser_token),
    )
    assert removed.status_code == 200
    assert removed.json()["affiliated"] is False


async def test_reminder_is_sent_once_per_day(
    db_session, owner_token, monkeypatch
):
    restaurant = await _make_restaurant(
        db_session, owner_token, date.today() + timedelta(days=5)
    )

    import app.services.affiliation_service as affiliation_service

    calls = []

    async def fake_send(db, user_id, title, body, data=None, style=None):
        calls.append({"user_id": user_id, "title": title, "body": body, "data": data})
        return {"sent": 1}

    monkeypatch.setattr(affiliation_service, "send_to_user", fake_send)

    sent = await affiliation_service.send_affiliation_reminders(db_session)
    assert sent == 1
    assert len(calls) == 1
    assert calls[0]["user_id"] == restaurant.owner_id
    assert "5 día" in calls[0]["body"]
    assert calls[0]["data"]["type"] == "affiliation"

    await db_session.refresh(restaurant)
    assert restaurant.affiliation_reminder_on == date.today()

    # El mismo día no se repite.
    sent_again = await affiliation_service.send_affiliation_reminders(db_session)
    assert sent_again == 0
    assert len(calls) == 1
