"""Tests for mandado tracking."""

import pytest
from httpx import AsyncClient


@pytest.fixture
async def user_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Mandado User", "email": "mandado@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def other_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Other Mandado User", "email": "mandado2@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


async def _create_mandado(client: AsyncClient, token: str) -> dict:
    resp = await client.post(
        "/api/v1/mandados",
        json={
            "description": "Comprar medicina en la farmacia del centro",
            "estimated_budget": 150,
            "delivery_address": "Calle Principal 123",
            "delivery_location": {"lat": 19.44, "lng": -99.14},
            "payment_method": "cash",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()


class TestMandadoTracking:
    async def test_tracking_for_owner(self, client: AsyncClient, user_token):
        mandado = await _create_mandado(client, user_token)
        resp = await client.get(
            f"/api/v1/mandados/{mandado['id']}/tracking",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert len(data["timeline"]) == 4
        assert data["timeline"][0]["completed"] is True
        assert data["destination"] == {"lat": 19.44, "lng": -99.14}
        assert float(data["estimated_total"]) > 0

    async def test_tracking_forbidden_for_other_user(
        self, client: AsyncClient, user_token, other_token,
    ):
        mandado = await _create_mandado(client, user_token)
        resp = await client.get(
            f"/api/v1/mandados/{mandado['id']}/tracking",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403
