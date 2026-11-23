"""Phone verification via signed link and admin WhatsApp helper."""

import uuid
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.user import User
from app.services import phone_verification_service


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str, phone: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Cuenta Teléfono",
            "email": email,
            "phone": phone,
            "password": "pass123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def test_phone_link_verifies(client, db_session):
    token = await _register(client, "phone1@test.com", "4121234567")
    me = await client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.json()["phone_verified"] is False

    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    link_token = phone_verification_service.make_token(user)
    resp = await client.get("/web/verify-phone", params={"token": link_token})
    assert resp.status_code == 200
    assert "WhatsApp verificado" in resp.text

    me = await client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.json()["phone_verified"] is True


async def test_phone_link_rejects_another_phone(client, db_session):
    token = await _register(client, "phone2@test.com", "4121234567")
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    link_token = phone_verification_service.make_token(user)

    user.phone = "4129999999"
    await db_session.commit()

    resp = await client.get("/web/verify-phone", params={"token": link_token})
    assert resp.status_code == 400
    me = await client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.json()["phone_verified"] is False


async def test_admin_gets_courier_whatsapp_link_and_phone_change_resets(client, db_session):
    admin = await _register(client, "admin-phone@test.com", "4120000000")
    admin_user = await db_session.get(
        User, uuid.UUID(decode_access_token(admin)["sub"])
    )
    admin_user.is_superuser = True
    await db_session.commit()

    created = await client.post(
        "/api/v1/admin/couriers",
        headers=_headers(admin),
        json={
            "name": "Repartidor WhatsApp",
            "email": "courier-wa@test.com",
            "phone": "4121234567",
            "password": "reparto123",
            "vehicle_type": "motorcycle",
            "payout_method": "cash",
        },
    )
    assert created.status_code == 201, created.text
    dp_id = created.json()["id"]

    link = await client.get(
        f"/api/v1/admin/couriers/{dp_id}/phone-verification",
        headers=_headers(admin),
    )
    assert link.status_code == 200, link.text
    data = link.json()
    assert data["phone"] == "4121234567"
    assert data["verified"] is False
    assert "/web/verify-phone?token=" in data["url"]

    token = parse_qs(urlparse(data["url"]).query)["token"][0]
    verified = await client.get("/web/verify-phone", params={"token": token})
    assert verified.status_code == 200

    listing = await client.get(
        "/api/v1/admin/couriers/locations", headers=_headers(admin)
    )
    row = next(r for r in listing.json() if r["id"] == dp_id)
    assert row["phone_verified"] is True

    changed = await client.patch(
        f"/api/v1/admin/couriers/{dp_id}",
        headers=_headers(admin),
        json={"phone": "4120000001"},
    )
    assert changed.status_code == 200, changed.text

    listing = await client.get(
        "/api/v1/admin/couriers/locations", headers=_headers(admin)
    )
    row = next(r for r in listing.json() if r["id"] == dp_id)
    assert row["phone_verified"] is False
