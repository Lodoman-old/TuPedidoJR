"""Doble factor (TOTP) y bloqueo por cuenta."""

import uuid

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.user import User
from app.services import totp_service


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin(client: AsyncClient, db_session):
    email = "admin-2fa@test.com"
    password = "pass123"
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin 2FA",
        "email": email,
        "password": password,
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return {"token": token, "email": email, "password": password}


async def _enable(client: AsyncClient, admin) -> tuple[str, list[str]]:
    setup = await client.post("/api/v1/auth/2fa/setup", headers=_headers(admin["token"]))
    assert setup.status_code == 200
    data = setup.json()
    enable = await client.post(
        "/api/v1/auth/2fa/enable",
        json={"code": totp_service.totp(data["secret"])},
        headers=_headers(admin["token"]),
    )
    assert enable.status_code == 200
    return data["secret"], data["recovery_codes"]


class TestTOTP:
    def test_code_roundtrip(self):
        secret = totp_service.generate_secret()
        code = totp_service.totp(secret)
        assert len(code) == 6
        assert totp_service.verify(secret, code)
        assert not totp_service.verify(secret, "000000")

    def test_recovery_codes_are_hashed(self):
        codes = totp_service.generate_recovery_codes()
        assert len(codes) == 8
        assert len({totp_service.hash_code(c) for c in codes}) == 8


class TestTwoFactorFlow:
    async def test_setup_returns_secret_uri_and_codes(self, client: AsyncClient, admin):
        setup = await client.post("/api/v1/auth/2fa/setup", headers=_headers(admin["token"]))
        assert setup.status_code == 200
        data = setup.json()
        assert data["secret"]
        assert data["otpauth_uri"].startswith("otpauth://totp/")
        assert len(data["recovery_codes"]) == 8

    async def test_login_requires_code_after_enabling(self, client: AsyncClient, admin):
        secret, _codes = await _enable(client, admin)

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": admin["email"], "password": admin["password"]},
        )
        assert login.status_code == 200
        body = login.json()
        assert body.get("requires_2fa") is True
        assert "access_token" not in body

        verify = await client.post(
            "/api/v1/auth/2fa/verify",
            json={"temp_token": body["temp_token"], "code": totp_service.totp(secret)},
        )
        assert verify.status_code == 200
        assert verify.json()["access_token"]

    async def test_wrong_code_is_rejected(self, client: AsyncClient, admin):
        await _enable(client, admin)
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": admin["email"], "password": admin["password"]},
        )
        temp = login.json()["temp_token"]
        verify = await client.post(
            "/api/v1/auth/2fa/verify",
            json={"temp_token": temp, "code": "000000"},
        )
        assert verify.status_code == 401

    async def test_recovery_code_is_single_use(self, client: AsyncClient, admin):
        _secret, codes = await _enable(client, admin)

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": admin["email"], "password": admin["password"]},
        )
        first = await client.post(
            "/api/v1/auth/2fa/verify",
            json={"temp_token": login.json()["temp_token"], "code": codes[0]},
        )
        assert first.status_code == 200

        login2 = await client.post(
            "/api/v1/auth/login",
            json={"email": admin["email"], "password": admin["password"]},
        )
        second = await client.post(
            "/api/v1/auth/2fa/verify",
            json={"temp_token": login2.json()["temp_token"], "code": codes[0]},
        )
        assert second.status_code == 401

    async def test_disable_requires_password_and_code(self, client: AsyncClient, admin):
        secret, _codes = await _enable(client, admin)

        bad = await client.post(
            "/api/v1/auth/2fa/disable",
            json={"password": "incorrecta", "code": totp_service.totp(secret)},
            headers=_headers(admin["token"]),
        )
        assert bad.status_code == 400

        ok = await client.post(
            "/api/v1/auth/2fa/disable",
            json={"password": admin["password"], "code": totp_service.totp(secret)},
            headers=_headers(admin["token"]),
        )
        assert ok.status_code == 200

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": admin["email"], "password": admin["password"]},
        )
        assert login.json().get("access_token")


class TestAccountLockout:
    async def test_locks_after_five_failures(self, client: AsyncClient):
        email = "bloqueo@test.com"
        await client.post("/api/v1/auth/register", json={
            "name": "Bloqueo",
            "email": email,
            "password": "pass123",
        })
        for _ in range(5):
            resp = await client.post(
                "/api/v1/auth/login", json={"email": email, "password": "mala"}
            )
            assert resp.status_code == 401

        locked = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "mala"}
        )
        assert locked.status_code == 429

        good = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "pass123"}
        )
        assert good.status_code == 429
