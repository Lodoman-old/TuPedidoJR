"""Panel de administración: usuarios registrados."""

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.restaurant import Restaurant
from app.models.user import User


async def _register(client: AsyncClient, name: str, email: str) -> str:
    resp = await client.post("/api/v1/auth/register", json={
        "name": name, "email": email, "password": "pass123",
    })
    assert resp.status_code == 201
    return resp.json()["access_token"]


@pytest.fixture
async def admin_token(client: AsyncClient, db_session):
    token = await _register(client, "Admin Usuarios", "admin-users@test.com")
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


@pytest.fixture
async def people(client: AsyncClient, db_session):
    owner_token = await _register(client, "Dueño Negocio", "owner-users@test.com")
    owner_id = decode_access_token(owner_token)["sub"]
    client_token = await _register(client, "Cliente Normal", "client-users@test.com")
    courier_token = await _register(client, "Repartidor Uno", "courier-users@test.com")
    courier_id = decode_access_token(courier_token)["sub"]

    db_session.add(Restaurant(
        id=uuid.uuid4(),
        owner_id=owner_id,
        name="Negocio de Prueba",
        business_type="store",
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle Prueba 1",
        affiliation_expires_at=date.today() + timedelta(days=365),
    ))
    db_session.add(DeliveryPerson(
        user_id=uuid.UUID(courier_id), vehicle_type="moto", is_available=True,
    ))
    await db_session.commit()
    return {
        "owner": owner_id,
        "client": decode_access_token(client_token)["sub"],
        "courier": courier_id,
        "client_token": client_token,
    }


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_requires_superuser(client: AsyncClient, people):
    resp = await client.get("/api/v1/admin/users", headers=_headers(people["client_token"]))
    assert resp.status_code == 403


async def test_lists_every_role(client: AsyncClient, admin_token, people):
    resp = await client.get("/api/v1/admin/users", headers=_headers(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 4
    assert data["summary"]["businesses"] >= 1
    assert data["summary"]["couriers"] >= 1
    assert data["summary"]["admins"] >= 1

    by_id = {item["id"]: item for item in data["items"]}
    assert "repartidor" in by_id[people["courier"]]["roles"]
    assert "negocio" in by_id[people["owner"]]["roles"]
    assert "cliente" in by_id[people["client"]]["roles"]
    assert by_id[people["owner"]]["businesses"][0]["name"] == "Negocio de Prueba"
    assert by_id[people["courier"]]["courier"]["vehicle_type"] == "moto"


async def test_filters_by_role_and_search(client: AsyncClient, admin_token, people):
    only_couriers = await client.get(
        "/api/v1/admin/users?role=repartidor", headers=_headers(admin_token),
    )
    assert only_couriers.status_code == 200
    assert all("repartidor" in item["roles"] for item in only_couriers.json()["items"])

    search = await client.get(
        "/api/v1/admin/users?q=client-users", headers=_headers(admin_token),
    )
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["email"] == "client-users@test.com"


async def test_users_page_renders(client: AsyncClient):
    resp = await client.get("/web/admin/users")
    assert resp.status_code == 200
    assert "Usuarios registrados" in resp.text
    assert "userSummary" in resp.text
