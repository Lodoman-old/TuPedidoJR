"""Registro de accesos: IP, usuario y pantalla."""
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import decode_access_token
from app.models.access_log import AccessLog
from app.models.user import User
from app.services.access_log_service import screen_label


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _from_ip(ip: str) -> dict:
    return {"X-Forwarded-For": ip}


async def _register(client: AsyncClient, email: str, name: str = "Cliente Accesos") -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "pass1234"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _make_admin(db_session, token: str) -> None:
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()


def test_screen_labels():
    assert screen_label("/web/admin/access") == "Admin · Accesos e IPs"
    assert screen_label("/web/orders/123") == "Mis pedidos"
    assert screen_label("/web/recargas/abc/ticket") == "Recargas"
    assert screen_label("/web/ruta-nueva") == "/web/ruta-nueva"


async def test_visit_records_ip_user_and_screen(client: AsyncClient, db_session):
    token = await _register(client, "accesos-cliente@test.com")
    ip = "198.51.100.77"

    resp = await client.post(
        "/api/v1/analytics/visit",
        json={"path": "/web/orders"},
        headers={**_headers(token), **_from_ip(ip)},
    )
    assert resp.status_code == 204

    row = await db_session.scalar(
        select(AccessLog)
        .where(AccessLog.ip == ip)
        .order_by(AccessLog.created_at.desc())
    )
    assert row is not None
    assert row.screen == "Mis pedidos"
    assert row.path == "/web/orders"
    assert row.role == "customer"
    assert str(row.user_id) == decode_access_token(token)["sub"]


async def test_admin_visits_are_also_recorded(client: AsyncClient, db_session):
    token = await _register(client, "accesos-admin-visita@test.com")
    await _make_admin(db_session, token)
    ip = "198.51.100.78"

    resp = await client.post(
        "/api/v1/analytics/visit",
        json={"path": "/web/admin/security"},
        headers={**_headers(token), **_from_ip(ip)},
    )
    assert resp.status_code == 204

    row = await db_session.scalar(select(AccessLog).where(AccessLog.ip == ip))
    assert row is not None
    assert row.role == "admin"
    assert row.screen == "Admin · Seguridad"


async def test_login_records_access(client: AsyncClient, db_session):
    email = "accesos-login@test.com"
    await _register(client, email)
    ip = "198.51.100.79"

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
        headers=_from_ip(ip),
    )
    assert resp.status_code == 200, resp.text

    row = await db_session.scalar(
        select(AccessLog)
        .where(AccessLog.ip == ip, AccessLog.path == "/web/login")
        .order_by(AccessLog.created_at.desc())
    )
    assert row is not None
    assert row.screen == "Inicio de sesión"


async def test_access_overview_lists_ips_and_screens(client: AsyncClient, db_session):
    admin_token = await _register(client, "accesos-admin@test.com", "Admin Accesos")
    await _make_admin(db_session, admin_token)
    user_token = await _register(client, "accesos-usuario@test.com")
    ip = "198.51.100.80"

    for path in ("/web/orders", "/web/recargas", "/web/orders"):
        await client.post(
            "/api/v1/analytics/visit",
            json={"path": path},
            headers={**_headers(user_token), **_from_ip(ip)},
        )

    resp = await client.get(
        "/api/v1/admin/security/access?days=7",
        headers=_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["totals"]["visits"] >= 3
    ip_row = next(row for row in data["ips"] if row["ip"] == ip)
    assert ip_row["visits"] == 3
    assert ip_row["users"] == 1
    assert "Mis pedidos" in ip_row["last_screen"]
    screens = {row["screen"] for row in data["screens"]}
    assert "Mis pedidos" in screens
    assert "Recargas" in screens
    assert any(
        visit["ip"] == ip and visit["screen"] == "Recargas"
        for visit in data["visits"]
    )

    filtered = await client.get(
        f"/api/v1/admin/security/access?days=7&ip={ip}",
        headers=_headers(admin_token),
    )
    assert filtered.status_code == 200
    assert all(row["ip"] == ip for row in filtered.json()["visits"])


async def test_access_overview_requires_admin(client: AsyncClient, db_session):
    token = await _register(client, "accesos-no-admin@test.com")
    resp = await client.get(
        "/api/v1/admin/security/access", headers=_headers(token)
    )
    assert resp.status_code == 403
