"""QR digital del negocio para imprimir y reenviar por correo."""

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.restaurant import Restaurant


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Dueño QR", "email": "owner-qr@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def business(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    resto = Restaurant(
        id=uuid.uuid4(),
        name="QR Negocio",
        slug="qr-negocio",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 5 de Mayo 100",
        is_open=True,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    await db_session.commit()
    return resto


@pytest.mark.asyncio
async def test_qr_svg(client: AsyncClient, business):
    resp = await client.get(f"/api/v1/restaurants/{business.id}/qr")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in resp.text


@pytest.mark.asyncio
async def test_qr_png_download(client: AsyncClient, business):
    resp = await client.get(
        f"/api/v1/restaurants/{business.id}/qr?format=png&download=1"
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(resp.content) > 500


@pytest.mark.asyncio
async def test_qr_print_page(client: AsyncClient, business):
    resp = await client.get(f"/web/restaurants/{business.id}/qr")
    assert resp.status_code == 200
    assert "/r/qr-negocio" in resp.text
    assert "Escanea y pide" in resp.text


@pytest.mark.asyncio
async def test_qr_unknown_business(client: AsyncClient):
    resp = await client.get(f"/api/v1/restaurants/{uuid.uuid4()}/qr")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_resends_qr_email(
    client: AsyncClient, business, owner_token, monkeypatch
):
    calls = []

    async def fake_send(db, to, subject, html, text=None, attachments=None):
        calls.append({"to": to, "subject": subject, "attachments": attachments})
        return True, "Correo enviado"

    monkeypatch.setattr("app.services.affiliation_qr_service.send_email", fake_send)

    resp = await client.post(
        f"/api/v1/restaurants/{business.id}/qr/email",
        headers=_headers(owner_token),
    )
    assert resp.status_code == 200
    assert resp.json()["sent"] is True
    assert calls[0]["to"] == "owner-qr@test.com"
    assert "QR" in calls[0]["subject"]
    filename, content, mime = calls[0]["attachments"][0]
    assert filename.endswith(".png")
    assert mime == "image/png"
    assert content.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_stranger_cannot_resend_qr(client: AsyncClient, business):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Ajeno", "email": "ajeno-qr@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    denied = await client.post(
        f"/api/v1/restaurants/{business.id}/qr/email",
        headers=_headers(token),
    )
    assert denied.status_code == 403
