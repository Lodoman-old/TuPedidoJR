"""Métricas de audiencia: visitas diarias y dispositivos push."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import decode_access_token
from app.models.daily_visit import DailyVisit
from app.models.push_token import PushToken
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Visitas", "email": "cliente-visitas@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Visitas", "email": "admin-visitas@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


@pytest.mark.asyncio
async def test_visit_counts_once_per_day(
    client: AsyncClient, customer_token, db_session
):
    for _ in range(2):
        resp = await client.post(
            "/api/v1/analytics/visit",
            json={"path": "/web/inicio"},
            headers=_headers(customer_token),
        )
        assert resp.status_code == 204

    rows = (
        await db_session.execute(
            select(DailyVisit).where(
                DailyVisit.user_id
                == uuid.UUID(decode_access_token(customer_token)["sub"])
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].role == "customer"
    assert rows[0].views == 2


@pytest.mark.asyncio
async def test_admin_visits_are_not_counted(
    client: AsyncClient, superuser_token, db_session
):
    resp = await client.post(
        "/api/v1/analytics/visit",
        json={"path": "/web/admin"},
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 204
    rows = (await db_session.execute(select(DailyVisit))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_audience_metrics_in_security_overview(
    client: AsyncClient, customer_token, superuser_token, db_session
):
    user_id = uuid.UUID(decode_access_token(customer_token)["sub"])
    db_session.add(PushToken(user_id=user_id, token="token-audiencia-1", platform="android"))
    await db_session.commit()

    await client.post(
        "/api/v1/analytics/visit",
        json={"path": "/web/inicio"},
        headers=_headers(customer_token),
    )
    await client.post(
        "/api/v1/analytics/visit",
        json={"path": "/web/restaurants"},
        headers=_headers(customer_token),
    )

    resp = await client.get(
        "/api/v1/admin/security/overview", headers=_headers(superuser_token)
    )
    assert resp.status_code == 200, resp.text
    audience = resp.json()["audience"]
    assert audience["push_devices"] == 1
    assert audience["push_users"] == 1
    assert audience["push_by_platform"]["android"] == 1
    assert audience["visits_today"] == 1
    assert audience["views_today"] == 2
    assert audience["normal_users"] >= 1
    assert len(audience["visits_7d"]) == 7
    assert audience["visits_7d"][-1]["users"] == 1
    assert audience["visits_7d"][-1]["views"] == 2
