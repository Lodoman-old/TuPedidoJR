"""Pantalla de usuarios en línea y última actividad."""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.restaurant import Restaurant
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, name: str, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "pass1234"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _user_id(token: str) -> uuid.UUID:
    return uuid.UUID(decode_access_token(token)["sub"])


async def _set_last_seen(db_session, token: str, minutes: int | None) -> None:
    user = await db_session.get(User, await _user_id(token))
    user.last_seen_at = (
        None
        if minutes is None
        else datetime.now(timezone.utc) - timedelta(minutes=minutes)
    )
    await db_session.commit()


async def test_online_requires_superuser(client: AsyncClient):
    token = await _register(client, "Cliente Online", "online-client@test.com")
    resp = await client.get(
        "/api/v1/admin/online-users", headers=_headers(token)
    )
    assert resp.status_code == 403


async def test_online_summary_roles_and_filters(client: AsyncClient, db_session):
    admin = await _register(client, "Admin Online", "online-admin@test.com")
    admin_user = await db_session.get(User, await _user_id(admin))
    admin_user.is_superuser = True
    await db_session.commit()

    owner = await _register(client, "Dueño Online", "online-owner@test.com")
    courier = await _register(client, "Repartidor Online", "online-courier@test.com")
    customer = await _register(client, "Cliente Nunca", "online-never@test.com")

    db_session.add(Restaurant(
        id=uuid.uuid4(),
        owner_id=await _user_id(owner),
        name="Negocio en Línea",
        business_type="store",
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle Prueba 2",
    ))
    db_session.add(DeliveryPerson(
        user_id=await _user_id(courier), vehicle_type="moto", is_available=True
    ))
    await db_session.commit()

    await _set_last_seen(db_session, admin, 1)
    await _set_last_seen(db_session, owner, 30)
    await _set_last_seen(db_session, courier, 180)
    await _set_last_seen(db_session, customer, None)

    resp = await client.get(
        "/api/v1/admin/online-users", headers=_headers(admin)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    summary = data["summary"]
    assert summary["total"] == 4
    assert summary["online"] == 1
    assert summary["recent"] == 1
    assert summary["offline"] == 1
    assert summary["never"] == 1
    assert summary["admins"] == 1
    assert summary["businesses"] == 1
    assert summary["couriers"] == 1
    assert summary["clients"] == 1
    assert data["online_window_minutes"] == 5

    presences = {row["email"]: row["presence"] for row in data["items"]}
    assert presences["online-admin@test.com"] == "online"
    assert presences["online-owner@test.com"] == "recent"
    assert presences["online-courier@test.com"] == "offline"
    assert presences["online-never@test.com"] == "never"

    roles = {row["email"]: row["roles"] for row in data["items"]}
    assert roles["online-owner@test.com"] == ["negocio"]
    assert roles["online-courier@test.com"] == ["repartidor"]
    assert roles["online-never@test.com"] == ["cliente"]
    assert roles["online-admin@test.com"] == ["admin"]

    only_online = await client.get(
        "/api/v1/admin/online-users?status=online", headers=_headers(admin)
    )
    assert only_online.status_code == 200
    assert [row["email"] for row in only_online.json()["items"]] == [
        "online-admin@test.com"
    ]

    only_couriers = await client.get(
        "/api/v1/admin/online-users?role=repartidor", headers=_headers(admin)
    )
    assert [row["email"] for row in only_couriers.json()["items"]] == [
        "online-courier@test.com"
    ]

    search = await client.get(
        "/api/v1/admin/online-users?q=nunca", headers=_headers(admin)
    )
    assert [row["email"] for row in search.json()["items"]] == [
        "online-never@test.com"
    ]


async def test_heartbeat_and_requests_update_last_seen(
    client: AsyncClient, db_session
):
    token = await _register(client, "Cliente Latido", "online-heartbeat@test.com")
    await _set_last_seen(db_session, token, 15)

    resp = await client.post("/api/v1/auth/heartbeat", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    user = await db_session.get(User, await _user_id(token))
    await db_session.refresh(user)
    last = user.last_seen_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    assert (datetime.now(timezone.utc) - last).total_seconds() < 60

    fresh = await client.get("/api/v1/admin/online-users", headers=_headers(token))
    assert fresh.status_code == 403
