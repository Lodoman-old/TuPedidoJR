"""Manuales: una guía por rol y manual del administrador restringido."""

import uuid

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.user import User


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Manuales",
        "email": "admin-manuales@test.com",
        "password": "pass123",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


async def test_index_lists_public_roles_only(client: AsyncClient):
    resp = await client.get("/manuales")
    assert resp.status_code == 200
    assert "/manuales/cliente" in resp.text
    assert "/manuales/restaurante" in resp.text
    assert "/manuales/repartidor" in resp.text
    assert "/manuales/admin" not in resp.text


async def test_client_manual_shows_only_client(client: AsyncClient):
    resp = await client.get("/manuales/cliente")
    assert resp.status_code == 200
    assert "Manual del cliente" in resp.text
    for other in [
        "/manuales/admin",
        "/manuales/restaurante",
        "/manuales/repartidor",
        "/manuales/menu",
    ]:
        assert other not in resp.text


async def test_courier_manual_shows_only_courier(client: AsyncClient):
    resp = await client.get("/manuales/repartidor")
    assert resp.status_code == 200
    assert "Manual del repartidor" in resp.text
    for other in [
        "/manuales/admin",
        "/manuales/cliente",
        "/manuales/restaurante",
        "/manuales/menu",
    ]:
        assert other not in resp.text


async def test_business_manual_keeps_its_own_pages(client: AsyncClient):
    resp = await client.get("/manuales/restaurante")
    assert resp.status_code == 200
    assert "Manual general del negocio" in resp.text
    assert "/manuales/menu" in resp.text
    assert "/manuales/pedidos" in resp.text
    assert "/manuales/envios" in resp.text
    assert "/manuales/admin" not in resp.text
    assert "/manuales/cliente" not in resp.text
    assert "/manuales/repartidor" not in resp.text


async def test_admin_manual_requires_superuser(client: AsyncClient):
    resp = await client.get("/manuales/admin")
    assert resp.status_code == 403
    assert "Administrar TuPedidoJR" not in resp.text
    assert "solo para administradores" in resp.text


async def test_admin_manual_rejects_invalid_token(client: AsyncClient):
    resp = await client.get("/manuales/admin", params={"token": "invalido"})
    assert resp.status_code == 403


async def test_admin_manual_with_superuser_token(client: AsyncClient, superuser_token):
    resp = await client.get("/manuales/admin", params={"token": superuser_token})
    assert resp.status_code == 200
    assert "Administrar TuPedidoJR" in resp.text
