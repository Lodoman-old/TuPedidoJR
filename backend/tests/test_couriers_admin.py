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

async def _new_courier(client, token, email="edit.courier@test.com"):
    resp = await client.post(
        "/api/v1/admin/couriers",
        json={
            "name": "Repartidor Editable",
            "email": email,
            "phone": "4120000000",
            "password": "reparto123",
            "vehicle_type": "motorcycle",
            "payout_method": "cash",
        },
        headers=_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_admin_edits_courier_phone(client: AsyncClient, superuser_token):
    created = await _new_courier(client, superuser_token, "edit.phone@test.com")

    resp = await client.patch(
        f"/api/v1/admin/couriers/{created['id']}",
        json={
            "name": "Repartidor Actualizado",
            "phone": "4129998877",
            "vehicle_type": "bike",
            "delivery_bonus_per_order": 7,
        },
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "Repartidor Actualizado"
    assert data["phone"] == "4129998877"
    assert data["vehicle_type"] == "bike"

    listing = await client.get(
        "/api/v1/admin/couriers/locations",
        headers=_headers(superuser_token),
    )
    row = next(c for c in listing.json() if c["id"] == created["id"])
    assert row["phone"] == "4129998877"
    assert row["is_active"] is True


async def test_admin_deactivates_and_reactivates(client: AsyncClient, superuser_token):
    created = await _new_courier(client, superuser_token, "edit.baja@test.com")

    login = await client.post("/api/v1/auth/login", json={
        "email": "edit.baja@test.com", "password": "reparto123",
    })
    assert login.status_code == 200

    resp = await client.patch(
        f"/api/v1/admin/couriers/{created['id']}",
        json={"is_active": False},
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False

    blocked = await client.post("/api/v1/auth/login", json={
        "email": "edit.baja@test.com", "password": "reparto123",
    })
    assert blocked.status_code in (401, 403)

    resp = await client.patch(
        f"/api/v1/admin/couriers/{created['id']}",
        json={"is_active": True},
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 200
    again = await client.post("/api/v1/auth/login", json={
        "email": "edit.baja@test.com", "password": "reparto123",
    })
    assert again.status_code == 200


async def test_admin_deletes_courier_without_history(client: AsyncClient, superuser_token):
    created = await _new_courier(client, superuser_token, "edit.delete@test.com")

    resp = await client.delete(
        f"/api/v1/admin/couriers/{created['id']}",
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 200, resp.text

    listing = await client.get(
        "/api/v1/admin/couriers/locations",
        headers=_headers(superuser_token),
    )
    assert all(c["id"] != created["id"] for c in listing.json())

    login = await client.post("/api/v1/auth/login", json={
        "email": "edit.delete@test.com", "password": "reparto123",
    })
    assert login.status_code in (401, 403)


async def test_admin_cannot_delete_courier_with_history(
    client: AsyncClient, db_session, superuser_token
):
    from datetime import date, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from app.models.order import Order
    from app.models.restaurant import Restaurant

    created = await _new_courier(client, superuser_token, "edit.history@test.com")
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Resto Historial",
        owner_id=uuid.uuid4(),
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Calle 1",
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    # El dueño debe existir; usamos un usuario real.
    admin = await db_session.scalar(
        select(User).where(User.email == "admin-couriers@test.com")
    )
    restaurant.owner_id = admin.id
    db_session.add(restaurant)
    await db_session.commit()

    order = Order(
        user_id=admin.id,
        restaurant_id=restaurant.id,
        delivery_person_id=uuid.UUID(created["id"]),
        status="delivered",
        subtotal=Decimal("100"),
        delivery_fee=Decimal("20"),
        total=Decimal("120"),
        delivery_address="Calle 1",
        delivery_location="SRID=4326;POINT(-99.13 19.43)",
        delivery_earnings=Decimal("20"),
        payment_method="cash",
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/admin/couriers/{created['id']}",
        headers=_headers(superuser_token),
    )
    assert resp.status_code == 400
    assert "historial" in resp.json()["detail"].lower()
