"""Desbloqueo de la app con huella y continuidad de sesión."""

from datetime import datetime, timezone

from httpx import AsyncClient

from app.core.security import decode_access_token


async def test_unlock_page_public(client: AsyncClient):
    resp = await client.get("/web/unlock")
    assert resp.status_code == 200
    text = resp.text
    assert "Entra a TuPedidoJR" in text
    assert "/web/login" in text
    assert "tupedidojr_bio" in text
    assert "tupedidojr_token" in text


async def test_landing_redirects_native_with_saved_session(client: AsyncClient):
    resp = await client.get("/web/inicio")
    assert resp.status_code == 200
    assert "/web/unlock" in resp.text


async def test_login_remembers_email_and_expired_notice(client: AsyncClient):
    resp = await client.get("/web/login")
    assert resp.status_code == 200
    text = resp.text
    assert "tupedidojr_email" in text
    assert "Tu sesión expiró" in text


async def test_device_token_is_long_lived_and_valid(client: AsyncClient):
    reg = await client.post("/api/v1/auth/register", json={
        "name": "Device Test",
        "email": "device@test.com",
        "password": "password123",
    })
    assert reg.status_code == 201
    token = reg.json()["access_token"]

    resp = await client.post(
        "/api/v1/auth/device-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    device_token = resp.json()["access_token"]
    assert device_token != token

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {device_token}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "device@test.com"

    payload = decode_access_token(device_token)
    assert payload is not None
    assert payload.get("dev") is True
    remaining = payload["exp"] - datetime.now(timezone.utc).timestamp()
    assert remaining > 300 * 24 * 3600


async def test_device_token_requires_session(client: AsyncClient):
    resp = await client.post("/api/v1/auth/device-token")
    assert resp.status_code in (401, 403)

