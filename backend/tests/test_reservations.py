"""Tests for table reservations, pre-orders and deposit rules."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.menu_item import MenuItem
from app.models.menu_option import MenuOption, MenuOptionGroup
from app.models.reservation import Reservation
from app.models.restaurant import Restaurant
from app.models.user import User


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Owner Reservas", "email": "owner-reservas@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Reservas", "email": "cliente-reservas@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Reservas", "email": "admin-reservas@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


@pytest.fixture
async def restaurant(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Reservas Resto",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 5 de Mayo 209",
        is_open=True,
        rating=4.5,
        delivery_radius_m=5000,
        delivery_fee=20.00,
        affiliation_expires_at=date.today() + timedelta(days=365),
        reservations_enabled=True,
        reservation_deposit_percent=20,
        reservation_min_advance_min=120,
        reservation_late_tolerance_min=60,
    )
    db_session.add(resto)
    item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        name="Taco de prueba",
        price=100.00,
        preparation_time_min=5,
        is_available=True,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(resto)
    await db_session.refresh(item)
    return resto, item


def _when(hours: int = 5) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class TestReservationCreation:
    async def test_table_only_has_no_deposit_and_cash_fee(
        self, client, restaurant, customer_token,
    ):
        resto, _ = restaurant
        resp = await client.post(
            f"/api/v1/restaurants/{resto.id}/reservations",
            json={"reservation_at": _when(), "party_size": 4, "items": []},
            headers=_headers(customer_token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "requested"
        assert data["deposit_status"] == "not_required"
        assert float(data["deposit_amount"]) == 0
        assert data["service_fee_cash"] is True
        assert data["service_fee_status"] == "pending"
        assert float(data["service_fee"]) == 5
        assert float(data["commission_amount"]) == 5

    async def test_preorder_charges_20_percent_deposit(
        self, client, restaurant, customer_token,
    ):
        resto, item = restaurant
        resp = await client.post(
            f"/api/v1/restaurants/{resto.id}/reservations",
            json={
                "reservation_at": _when(),
                "party_size": 2,
                "items": [{"menu_item_id": str(item.id), "quantity": 2, "option_ids": []}],
                "deposit_method": "transfer",
            },
            headers=_headers(customer_token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "pending_deposit"
        assert data["deposit_status"] == "pending"
        assert float(data["preorder_subtotal"]) == 200
        assert float(data["deposit_amount"]) == 40
        assert float(data["remaining_to_charge"]) == 160
        assert data["service_fee_cash"] is False
        assert data["service_fee_status"] == "paid_online"

    async def test_minimum_advance_is_enforced(self, client, restaurant, customer_token):
        resto, _ = restaurant
        resp = await client.post(
            f"/api/v1/restaurants/{resto.id}/reservations",
            json={"reservation_at": _when(hours=1), "party_size": 2, "items": []},
            headers=_headers(customer_token),
        )
        assert resp.status_code == 400
        assert "anticipación" in resp.json()["detail"]

    async def test_preorder_with_options_is_saved_as_json(
        self, client, restaurant, customer_token, db_session,
    ):
        resto, item = restaurant
        group = MenuOptionGroup(
            menu_item_id=item.id,
            name="Tamaño",
            selection_type="single",
            is_required=True,
            min_selections=1,
            max_selections=1,
        )
        db_session.add(group)
        await db_session.flush()
        option = MenuOption(
            group_id=group.id,
            name="Mediana",
            price_delta=20,
            is_available=True,
        )
        db_session.add(option)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/restaurants/{resto.id}/reservations",
            json={
                "reservation_at": _when(),
                "party_size": 2,
                "items": [{
                    "menu_item_id": str(item.id),
                    "quantity": 1,
                    "option_ids": [str(option.id)],
                }],
                "deposit_method": "transfer",
            },
            headers=_headers(customer_token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert float(data["preorder_subtotal"]) == 120
        assert data["preorder_items"][0]["options"][0]["portion"] == 1.0
        assert float(data["deposit_amount"]) == 24


class TestReservationFlow:
    async def _create_preorder(self, client, restaurant, customer_token):
        resto, item = restaurant
        resp = await client.post(
            f"/api/v1/restaurants/{resto.id}/reservations",
            json={
                "reservation_at": _when(),
                "party_size": 2,
                "items": [{"menu_item_id": str(item.id), "quantity": 1, "option_ids": []}],
                "deposit_method": "transfer",
            },
            headers=_headers(customer_token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def test_restaurant_cannot_confirm_before_deposit(
        self, client, restaurant, customer_token, owner_token, superuser_token,
    ):
        resto, _ = restaurant
        reservation = await self._create_preorder(client, restaurant, customer_token)
        resp = await client.patch(
            f"/api/v1/restaurants/{resto.id}/reservations/{reservation['id']}/status",
            json={"status": "confirmed"},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 400
        assert "depósito" in resp.json()["detail"].lower()

        confirmed = await client.post(
            f"/api/v1/admin/reservation-deposits/{reservation['id']}/confirm",
            headers=_headers(superuser_token),
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["deposit_status"] == "paid"

        resp = await client.patch(
            f"/api/v1/restaurants/{resto.id}/reservations/{reservation['id']}/status",
            json={"status": "confirmed"},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "confirmed"

    async def test_early_cancel_refunds_deposit(
        self, client, restaurant, customer_token, superuser_token,
    ):
        resto, _ = restaurant
        reservation = await self._create_preorder(client, restaurant, customer_token)
        await client.post(
            f"/api/v1/admin/reservation-deposits/{reservation['id']}/confirm",
            headers=_headers(superuser_token),
        )
        resp = await client.post(
            f"/api/v1/reservations/{reservation['id']}/cancel",
            json={"reason": "Cambio de planes"},
            headers=_headers(customer_token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["deposit_status"] == "refund_pending"

    async def test_late_cancel_retains_deposit(
        self, client, restaurant, customer_token, superuser_token, db_session,
    ):
        resto, _ = restaurant
        reservation = await self._create_preorder(client, restaurant, customer_token)
        await client.post(
            f"/api/v1/admin/reservation-deposits/{reservation['id']}/confirm",
            headers=_headers(superuser_token),
        )
        row = await db_session.get(Reservation, uuid.UUID(reservation["id"]))
        row.reservation_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/reservations/{reservation['id']}/cancel",
            json={"reason": "Cancelación tardía"},
            headers=_headers(customer_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["deposit_status"] == "retained"

    async def test_deposit_transfer_settles_commission(
        self, client, restaurant, customer_token, superuser_token,
    ):
        reservation = await self._create_preorder(client, restaurant, customer_token)
        await client.post(
            f"/api/v1/admin/reservation-deposits/{reservation['id']}/confirm",
            headers=_headers(superuser_token),
        )
        resp = await client.post(
            f"/api/v1/admin/reservation-deposits/{reservation['id']}/transfer",
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["deposit_settlement_status"] == "transferred"
        assert data["commission_status"] == "settled"
        assert float(data["net_deposit_to_restaurant"]) == 15

