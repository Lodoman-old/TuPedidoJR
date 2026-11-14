"""Tests for business shipments (motomandado de negocio)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.restaurant import Restaurant
from app.models.user import User

LOCATION = {"lat": 20.6450, "lng": -100.9940}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Tienda Envíos", "email": "shipments-store@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def other_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Otro Usuario", "email": "shipments-other@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def store(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    row = Restaurant(
        id=uuid.uuid4(),
        name="Tienda de Ropa",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.9900 20.6400)",
        address="Calle 5 de Mayo 100",
        business_type="store",
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def courier(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Repartidor Envíos", "email": "shipments-courier@test.com",
        "password": "pass123",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    dp = DeliveryPerson(user_id=user.id, vehicle_type="motorcycle", is_available=True)
    db_session.add(dp)
    await db_session.commit()
    await db_session.refresh(dp)
    return token, dp


async def _quote(client, token, store, collect=0, paid_by="store"):
    return await client.post(
        f"/api/v1/restaurants/{store.id}/shipments/quote",
        json={
            "delivery_location": LOCATION,
            "collect_amount": collect,
            "shipping_paid_by": paid_by,
        },
        headers=_headers(token),
    )


async def _create(client, token, store, collect=250, paid_by="store", **extra):
    body = {
        "recipient_name": "Ana López",
        "recipient_phone": "4121234567",
        "delivery_address": "Calle Principal 123",
        "delivery_location": LOCATION,
        "package_description": "Paquete de ropa",
        "declared_value": 250,
        "collect_amount": collect,
        "shipping_paid_by": paid_by,
    }
    body.update(extra)
    return await client.post(
        f"/api/v1/restaurants/{store.id}/shipments",
        json=body,
        headers=_headers(token),
    )


async def _accept_pickup(client, token, shipment_id):
    accept = await client.patch(
        f"/api/v1/delivery/shipments/{shipment_id}/accept", headers=_headers(token)
    )
    assert accept.status_code == 200, accept.text
    pickup = await client.patch(
        f"/api/v1/delivery/shipments/{shipment_id}/pickup",
        json={"pickup_photo_url": None},
        headers=_headers(token),
    )
    assert pickup.status_code == 200, pickup.text


class TestShipmentStore:
    async def test_quote_matches_created_shipment(self, client, owner_token, store):
        quote = await _quote(client, owner_token, store, collect=250)
        assert quote.status_code == 200, quote.text
        q = quote.json()
        assert Decimal(q["platform_fee"]) == Decimal("10.00")
        assert Decimal(q["amount_to_collect"]) == Decimal("250.00")
        assert Decimal(q["store_charge"]) == Decimal(q["delivery_fee"]) + Decimal("10.00")

        created = await _create(client, owner_token, store, collect=250)
        assert created.status_code == 201, created.text
        s = created.json()
        assert s["status"] == "pending"
        assert len(s["delivery_code"]) == 4
        assert len(s["pickup_code"]) == 6
        assert s["public_token"]
        assert Decimal(s["delivery_fee"]) == Decimal(q["delivery_fee"])
        assert Decimal(s["store_charge"]) == Decimal(q["store_charge"])

    async def test_shipping_paid_by_recipient_adds_to_collect(
        self, client, owner_token, store
    ):
        quote = await _quote(client, owner_token, store, collect=100, paid_by="recipient")
        assert quote.status_code == 200, quote.text
        q = quote.json()
        assert Decimal(q["amount_to_collect"]) == Decimal("100.00") + Decimal(q["delivery_fee"])
        assert Decimal(q["store_charge"]) == Decimal("10.00")

    async def test_cod_cap_blocks_large_collections(self, client, owner_token, store):
        resp = await _create(client, owner_token, store, collect=2000)
        assert resp.status_code == 400
        assert "contra entrega" in resp.text.lower()

    async def test_other_user_cannot_list_or_create(self, client, other_token, store):
        listed = await client.get(
            f"/api/v1/restaurants/{store.id}/shipments", headers=_headers(other_token)
        )
        assert listed.status_code == 403
        created = await _create(client, other_token, store)
        assert created.status_code == 403

    async def test_cancel_only_before_pickup(self, client, owner_token, store):
        created = (await _create(client, owner_token, store)).json()
        resp = await client.post(
            f"/api/v1/restaurants/{store.id}/shipments/{created['id']}/cancel",
            json={"reason": "El cliente canceló"},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cancelled"


class TestShipmentCourier:
    async def test_courier_accepts_pickup_and_delivers_with_code(
        self, client, owner_token, store, courier, db_session
    ):
        token, dp = courier
        created = (await _create(client, owner_token, store, collect=250)).json()

        available = await client.get("/api/v1/delivery/shipments", headers=_headers(token))
        assert available.status_code == 200
        assert any(x["id"] == created["id"] for x in available.json())

        await _accept_pickup(client, token, created["id"])

        public = await client.get(f"/api/v1/shipments/public/{created['public_token']}")
        assert public.status_code == 200
        assert public.json()["delivery_code"] == created["delivery_code"]

        delivered = await client.patch(
            f"/api/v1/delivery/shipments/{created['id']}/deliver",
            json={"delivery_code": created["delivery_code"], "cash_collected": 250},
            headers=_headers(token),
        )
        assert delivered.status_code == 200, delivered.text
        s = delivered.json()
        assert s["status"] == "delivered"
        assert s["cod_status"] == "collected"
        assert Decimal(s["store_credit"]) == Decimal("250.00")
        assert Decimal(s["courier_earnings"]) == Decimal(s["delivery_fee"])

        await db_session.refresh(dp)
        expected_debt = Decimal("250.00") - Decimal(s["courier_earnings"])
        assert Decimal(dp.pending_platform_debt) == expected_debt

        after = await client.get(f"/api/v1/shipments/public/{created['public_token']}")
        assert after.json()["status"] == "delivered"
        assert after.json()["delivery_code"] is None

    async def test_shipping_paid_by_recipient_is_not_double_paid(
        self, client, owner_token, store, courier, db_session
    ):
        token, dp = courier
        created = (await _create(
            client, owner_token, store, collect=100, paid_by="recipient"
        )).json()
        await _accept_pickup(client, token, created["id"])
        delivered = await client.patch(
            f"/api/v1/delivery/shipments/{created['id']}/deliver",
            json={
                "delivery_code": created["delivery_code"],
                "cash_collected": created["amount_to_collect"],
            },
            headers=_headers(token),
        )
        assert delivered.status_code == 200, delivered.text
        s = delivered.json()
        assert Decimal(s["store_credit"]) == Decimal("100.00")
        assert Decimal(s["store_charge"]) == Decimal("10.00")
        await db_session.refresh(dp)
        assert Decimal(dp.pending_platform_debt) == Decimal("100.00")

    async def test_delivery_requires_code_or_photo(
        self, client, owner_token, store, courier
    ):
        token, _dp = courier
        created = (await _create(client, owner_token, store)).json()
        await _accept_pickup(client, token, created["id"])
        resp = await client.patch(
            f"/api/v1/delivery/shipments/{created['id']}/deliver",
            json={},
            headers=_headers(token),
        )
        assert resp.status_code == 400

    async def test_failed_delivery_charges_half_shipping(
        self, client, owner_token, store, courier
    ):
        token, _dp = courier
        created = (await _create(client, owner_token, store)).json()
        await _accept_pickup(client, token, created["id"])
        failed = await client.patch(
            f"/api/v1/delivery/shipments/{created['id']}/fail",
            json={"reason": "El cliente no estaba"},
            headers=_headers(token),
        )
        assert failed.status_code == 200, failed.text
        s = failed.json()
        assert s["status"] == "failed"
        assert Decimal(s["return_fee"]) == (
            Decimal(s["delivery_fee"]) * Decimal("0.50")
        ).quantize(Decimal("0.01"))
        assert Decimal(s["courier_earnings"]) == Decimal(s["return_fee"])

    async def test_non_courier_cannot_accept(self, client, owner_token, other_token, store):
        created = (await _create(client, owner_token, store)).json()
        resp = await client.patch(
            f"/api/v1/delivery/shipments/{created['id']}/accept",
            headers=_headers(other_token),
        )
        assert resp.status_code == 403
