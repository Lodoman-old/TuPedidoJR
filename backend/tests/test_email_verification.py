"""Email verification and public registration protections."""

import uuid

from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.user import User
from app.services.email_verification_service import make_token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Cuenta Nueva",
            "email": email,
            "phone": "4121234567",
            "password": "pass123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def test_register_starts_unverified_and_link_verifies(client, db_session):
    token = await _register(client, "verifica@test.com")
    me = await client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.status_code == 200
    assert me.json()["email_verified"] is False

    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    verify_token = make_token(user)
    verified = await client.post(
        "/api/v1/auth/verify-email", json={"token": verify_token}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verified"] is True

    me = await client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.json()["email_verified"] is True


async def test_verify_email_rejects_invalid_token(client):
    resp = await client.post(
        "/api/v1/auth/verify-email", json={"token": "not-a-valid-token"}
    )
    assert resp.status_code == 400


async def test_web_verify_email_page(client, db_session):
    token = await _register(client, "webverify@test.com")
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    resp = await client.get("/web/verify-email", params={"token": make_token(user)})
    assert resp.status_code == 200
    assert "Correo confirmado" in resp.text


async def test_web_verify_email_page_rejects_bad_token(client):
    resp = await client.get("/web/verify-email", params={"token": "bad"})
    assert resp.status_code == 400
    assert "No pudimos confirmar" in resp.text


async def test_registration_honeypot_rejected(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Bot",
            "email": "bot@test.com",
            "phone": "4121234567",
            "password": "pass123",
            "website": "https://spam.example",
        },
    )
    assert resp.status_code == 400
