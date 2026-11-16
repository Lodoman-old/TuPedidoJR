"""Seguridad: escaneos, bloqueo automático y panel del administrador."""

import uuid

import pytest
from httpx import AsyncClient
from starlette.datastructures import Address

from app.core.security import decode_access_token
from app.models.setting import Setting
from app.models.user import User
from app.services.security_service import (
    client_ip,
    is_suspicious_path,
    security_guard,
)


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Seguridad",
        "email": "admin-seguridad@test.com",
        "password": "pass123",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _from_ip(ip: str) -> dict:
    return {"X-Forwarded-For": ip}


class TestPathDetection:
    def test_client_ip_ignores_cloudflare_by_default(self):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "headers": [(b"cf-connecting-ip", b"203.0.113.5")],
            "client": ("127.0.0.1", 1234),
        }
        request = Request(scope)
        assert client_ip(request) == "127.0.0.1"
        assert client_ip(request, trust_cf=True) == "203.0.113.5"

    def test_client_ip_uses_peer_when_public(self):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "headers": [(b"cf-connecting-ip", b"203.0.113.5")],
            "client": ("8.8.8.8", 1234),
        }
        request = Request(scope)
        assert client_ip(request, trust_cf=True) == "8.8.8.8"

    def test_detects_scan_paths(self):
        paths = [
            "/.env",
            "/.git/config",
            "/wp-login.php",
            "/wp-admin/",
            "/phpmyadmin/",
            "/etc/passwd",
            "/../../etc/passwd",
            "/index.php?x=union select 1",
            "/search?q=<script>alert(1)</script>",
        ]
        for path in paths:
            assert is_suspicious_path(path), path

    def test_allows_normal_paths(self):
        paths = [
            "/web/inicio",
            "/manuales/cliente",
            "/api/v1/restaurants",
            "/r/mi-negocio",
            "/api/v1/orders",
        ]
        for path in paths:
            assert not is_suspicious_path(path), path


class TestAutoBlock:
    async def test_scan_blocks_the_ip(self, client: AsyncClient):
        ip = "198.51.100.7"
        first = await client.get("/.env", headers=_from_ip(ip))
        assert first.status_code == 403
        assert security_guard.is_blocked(ip)

        blocked = await client.get("/web/inicio", headers=_from_ip(ip))
        assert blocked.status_code == 403

    async def test_whitelisted_ip_is_not_blocked(self, client: AsyncClient, db_session):
        db_session.add(Setting(key="SECURITY_WHITELIST", value="198.51.100.9"))
        await db_session.commit()
        security_guard.reset_settings_cache()

        scan = await client.get("/.env", headers=_from_ip("198.51.100.9"))
        assert scan.status_code == 404
        assert not security_guard.is_blocked("198.51.100.9")

        ok = await client.get("/web/inicio", headers=_from_ip("198.51.100.9"))
        assert ok.status_code == 200

    async def test_content_flood_blocks_the_ip(self, client: AsyncClient):
        from collections import deque
        import time as clock

        ip = "198.51.100.33"
        security_guard._content[ip] = deque([clock.time()] * 200)

        first = await client.get("/api/v1/restaurants", headers=_from_ip(ip))
        assert first.status_code == 200
        blocked = await client.get("/web/inicio", headers=_from_ip(ip))
        assert blocked.status_code == 403
        assert security_guard.is_blocked(ip)

    async def test_normal_navigation_is_not_blocked(self, client: AsyncClient):
        resp = await client.get("/web/inicio")
        assert resp.status_code == 200


class TestWebSocketGuard:
    class FakeWS:
        headers = {}
        client = Address("203.0.113.9", 1234)

        def __init__(self):
            self.closed = None

        async def close(self, code=1000, reason=None):
            self.closed = code

    async def test_blocked_ip_is_rejected(self, db_session):
        from app.services.security_service import check_websocket

        await security_guard.block("203.0.113.9", 5, "test", auto=False)
        ws = self.FakeWS()
        assert await check_websocket(ws) is True
        assert ws.closed == 4403

    async def test_allowed_ip_passes(self, db_session):
        from app.services.security_service import check_websocket

        ws = self.FakeWS()
        ws.client = Address("203.0.113.10", 1234)
        assert await check_websocket(ws) is False
        assert ws.closed is None


class TestAdminSecurity:
    async def test_overview_requires_admin(self, client: AsyncClient):
        resp = await client.get("/api/v1/admin/security/overview")
        assert resp.status_code in (401, 403)

    async def test_overview_returns_data(self, client: AsyncClient, superuser_token):
        resp = await client.get(
            "/api/v1/admin/security/overview", headers=_headers(superuser_token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "counters" in body
        assert "blocks" in body
        assert "events" in body
        assert "settings" in body

    async def test_manual_block_and_unblock(self, client: AsyncClient, superuser_token):
        headers = _headers(superuser_token)
        ip = "203.0.113.50"

        blocked = await client.post(
            "/api/v1/admin/security/block",
            json={"ip": ip, "minutes": 30, "reason": "prueba"},
            headers=headers,
        )
        assert blocked.status_code == 200
        assert (await client.get("/web/inicio", headers=_from_ip(ip))).status_code == 403

        overview = await client.get("/api/v1/admin/security/overview", headers=headers)
        assert any(item["ip"] == ip for item in overview.json()["blocks"])

        unblocked = await client.post(
            "/api/v1/admin/security/unblock", json={"ip": ip}, headers=headers
        )
        assert unblocked.status_code == 200
        assert (await client.get("/web/inicio", headers=_from_ip(ip))).status_code == 200

    async def test_invalid_ip_is_rejected(self, client: AsyncClient, superuser_token):
        resp = await client.post(
            "/api/v1/admin/security/block",
            json={"ip": "no-es-una-ip", "minutes": 30},
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 400

    async def test_admin_page_loads(self, client: AsyncClient):
        resp = await client.get("/web/admin/security")
        assert resp.status_code == 200
        assert "Seguridad y bloqueos" in resp.text
