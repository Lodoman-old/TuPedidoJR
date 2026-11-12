"""Alta de repartidores desde el panel de administración."""

import uuid

import pytest
from httpx import AsyncClient

from app.models.delivery_person import DeliveryPerson
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Repartidores", "email": "admin-couriers@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    from app.core.security import decode_access_token
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


async def test_admin_creates_courier(
    client: AsyncClient, db_session, superuser_token
):
    resp = await client.post(
        "/api/v1/admin/couriers",
        json={
            "name": "Juan Repartidor",
            "email": "juan.repartidor@test.com",
            "phone": "4121234567",
            "password": "reparto123",
            "vehicle_type": "motorcycle",
            "payout_method": "cash",
            "is_mandadero": True,
            "delivery_bonus_per_order": 5,
        },
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Juan Repartidor"

    from sqlalchemy import select
    user = await db_session.scalar(
        select(User).where(User.email == "juan.repartidor@test.com")
    )
    assert user is not None
    courier = await db_session.scalar(
        select(DeliveryPerson).where(DeliveryPerson.user_id == user.id)
    )
    assert courier is not None
    assert courier.vehicle_type == "motorcycle"
    assert courier.is_mandadero is True

    # Puede iniciar sesión con las credenciales creadas.
    login = await client.post("/api/v1/auth/login", json={
        "email": "juan.repartidor@test.com", "password": "reparto123",
    })
    assert login.status_code == 200
    profile = await client.get(
        "/api/v1/delivery/profile",
        headers=_headers(login.json()["access_token"]),
    )
    assert profile.status_code == 200

    # No se permite duplicar el correo.
    duplicate = await client.post(
        "/api/v1/admin/couriers",
        json={
            "name": "Otro Juan",
            "email": "juan.repartidor@test.com",
            "password": "reparto123",
            "vehicle_type": "bike",
        },
        headers=_headers(superuser_token),
    )
    assert duplicate.status_code == 400


async def test_transfer_courier_requires_clabe(
    client: AsyncClient, superuser_token
):
    resp = await client.post(
        "/api/v1/admin/couriers",
        json={
            "name": "María Repartidora",
            "email": "maria.repartidora@test.com",
            "password": "reparto123",
            "vehicle_type": "car",
            "payout_method": "transfer",
            "bank_name": "BBVA",
            "bank_account_holder": "María",
            "bank_clabe": "123",
        },
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 400
    assert "CLABE" in resp.json()["detail"]
