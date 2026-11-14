"""Tests for mandado tracking."""

import uuid

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.setting import Setting
from app.models.user import User


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


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Mandados", "email": "admin-mandados@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(
        User, uuid.UUID(decode_access_token(token)["sub"])
    )
    user.is_superuser = True
    await db_session.commit()
    return token


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


class TestMandadoPrepayment:
    async def test_high_value_cash_requires_prepayment(
        self, client: AsyncClient, user_token
    ):
        resp = await client.post(
            "/api/v1/mandados",
            json={
                "description": "Comprar una pantalla y un teclado",
                "estimated_budget": 1000,
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.44, "lng": -99.14},
                "payment_method": "cash",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 400
        assert "transferencia" in resp.json()["detail"].lower()

    async def test_high_value_transfer_stays_pending_payment(
        self, client: AsyncClient, user_token, db_session
    ):
        db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
        await db_session.commit()
        resp = await client.post(
            "/api/v1/mandados",
            json={
                "description": "Comprar una pantalla y un teclado",
                "estimated_budget": 1000,
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.44, "lng": -99.14},
                "payment_method": "transfer",
                "payment_proof_url": "/static/uploads/test.png",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "pending_payment"
        assert data["prepayment_required"] is True
        assert data["payment_status"] == "pending"

    async def test_trusted_customer_can_pay_cash(
        self, client: AsyncClient, user_token, db_session
    ):
        user = await db_session.get(
            User, uuid.UUID(decode_access_token(user_token)["sub"])
        )
        user.trusted_customer = True
        await db_session.commit()
        resp = await client.post(
            "/api/v1/mandados",
            json={
                "description": "Comprar una pantalla y un teclado",
                "estimated_budget": 1200,
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.44, "lng": -99.14},
                "payment_method": "cash",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "pending"

    async def test_admin_confirms_prepayment(
        self, client: AsyncClient, user_token, superuser_token, db_session
    ):
        db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
        await db_session.commit()
        created = await client.post(
            "/api/v1/mandados",
            json={
                "description": "Comprar una pantalla y un teclado",
                "estimated_budget": 1000,
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.44, "lng": -99.14},
                "payment_method": "transfer",
                "payment_proof_url": "/static/uploads/test.png",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert created.status_code == 201, created.text
        mandado_id = created.json()["id"]

        pending = await client.get(
            "/api/v1/admin/mandados/prepayments",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert pending.status_code == 200
        assert any(row["id"] == mandado_id for row in pending.json())

        confirmed = await client.post(
            f"/api/v1/admin/mandados/{mandado_id}/confirm-payment",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["payment_status"] == "paid"
        assert confirmed.json()["advance_status"] == "pending"
        assert confirmed.json()["advance_amount"] == "1000.00"

        early_advance = await client.post(
            f"/api/v1/admin/mandados/{mandado_id}/advance-delivered",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert early_advance.status_code == 400

        detail = await client.get(
            f"/api/v1/mandados/{mandado_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == "pending"

    async def test_courier_confirms_pickup(
        self, client: AsyncClient, user_token, db_session
    ):
        created = await client.post(
            "/api/v1/mandados",
            json={
                "description": "Comprar leche y pan",
                "estimated_budget": 100,
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.44, "lng": -99.14},
                "payment_method": "cash",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert created.status_code == 201, created.text
        mandado_id = created.json()["id"]

        courier_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "name": "Mandadero Pickup",
                "email": "mandadero-pickup@test.com",
                "password": "pass123",
            },
        )
        courier_token = courier_resp.json()["access_token"]
        courier_user = await db_session.get(
            User, uuid.UUID(decode_access_token(courier_token)["sub"])
        )
        courier = DeliveryPerson(
            user_id=courier_user.id,
            vehicle_type="motorcycle",
            is_mandadero=True,
        )
        db_session.add(courier)
        await db_session.flush()

        from app.models.mandado import Mandado
        mandado = await db_session.get(Mandado, uuid.UUID(mandado_id))
        mandado.status = "accepted"
        mandado.delivery_person_id = courier.id
        await db_session.commit()

        pickup = await client.post(
            f"/api/v1/mandados/{mandado_id}/pickup",
            json={
                "pickup_address": "Tienda de la esquina",
                "pickup_location": {"lat": 19.43, "lng": -99.13},
            },
            headers={"Authorization": f"Bearer {courier_token}"},
        )
        assert pickup.status_code == 200, pickup.text
        data = pickup.json()
        assert data["pickup_address"] == "Tienda de la esquina"
        assert data["delivery_fee_final"] is not None
        assert data["fee_adjustment_status"] in (
            "absorbed", "pending_customer", "refund_pending",
        )

    async def test_advance_delivered_and_settled(
        self, client: AsyncClient, user_token, superuser_token, db_session
    ):
        db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
        await db_session.commit()
        created = await client.post(
            "/api/v1/mandados",
            json={
                "description": "Comprar una pantalla y un teclado",
                "estimated_budget": 1000,
                "delivery_address": "Calle Principal 123",
                "delivery_location": {"lat": 19.44, "lng": -99.14},
                "payment_method": "transfer",
                "payment_proof_url": "/static/uploads/test.png",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert created.status_code == 201, created.text
        mandado_id = created.json()["id"]
        await client.post(
            f"/api/v1/admin/mandados/{mandado_id}/confirm-payment",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )

        courier_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "name": "Mandadero Prueba",
                "email": "mandadero-advance@test.com",
                "password": "pass123",
            },
        )
        courier_token = courier_resp.json()["access_token"]
        courier_user = await db_session.get(
            User, uuid.UUID(decode_access_token(courier_token)["sub"])
        )
        courier = DeliveryPerson(
            user_id=courier_user.id,
            vehicle_type="motorcycle",
            is_mandadero=True,
        )
        db_session.add(courier)
        await db_session.flush()

        from datetime import datetime, timezone
        from app.models.mandado import Mandado
        mandado = await db_session.get(Mandado, uuid.UUID(mandado_id))
        mandado.status = "accepted"
        mandado.delivery_person_id = courier.id
        mandado.pickup_address = "Tienda de prueba"
        mandado.pickup_confirmed_at = datetime.now(timezone.utc)
        await db_session.commit()

        delivered = await client.post(
            f"/api/v1/admin/mandados/{mandado_id}/advance-delivered",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert delivered.status_code == 200, delivered.text
        assert delivered.json()["advance_status"] == "delivered"

        purchased = await client.patch(
            f"/api/v1/mandados/{mandado_id}/purchase",
            json={
                "product_total": 900,
                "receipt_photo_url": "/static/uploads/receipt.png",
            },
            headers={"Authorization": f"Bearer {courier_token}"},
        )
        assert purchased.status_code == 200, purchased.text
        assert purchased.json()["advance_status"] == "used"
        assert purchased.json()["advance_difference"] == "-100.00"

        settled = await client.post(
            f"/api/v1/admin/mandados/{mandado_id}/advance-settle",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["advance_status"] == "settled"


class TestMandadoTracking:
    async def test_estimate_uses_fixed_risk_fee(self, client: AsyncClient, user_token):
        resp = await client.post(
            "/api/v1/mandados/estimate",
            json={
                "estimated_budget": 200,
                "delivery_location": {"lat": 19.44, "lng": -99.14},
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert float(data["risk_fee"]) == 15
        assert float(data["platform_fee"]) == 0
        assert float(data["estimated_total"]) == (
            200 + float(data["delivery_fee"]) + 15
        )

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
