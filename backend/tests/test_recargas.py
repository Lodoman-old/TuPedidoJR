"""Recargas: función en pausa y acciones sobre registros anteriores."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services import recarga_service, recarga_ticket_service, sivetel_service
from app.services.setting_service import set_setting


@pytest.fixture(autouse=True)
def _fake_provider_status(monkeypatch):
    async def fake_status(client):
        return {"available": True, "message": ""}

    monkeypatch.setattr(sivetel_service, "provider_status", fake_status)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _courier(db_session, token: str) -> DeliveryPerson:
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    return await db_session.scalar(
        select(DeliveryPerson).where(DeliveryPerson.user_id == user_id)
    )


@pytest.fixture
async def courier_account(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Courier Recargas", "email": "courier-rec@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    db_session.add(DeliveryPerson(user_id=user_id, vehicle_type="motorcycle", is_available=True))
    await db_session.commit()
    return token


@pytest.fixture
async def admin_account(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Recargas", "email": "admin-rec@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


async def test_courier_payout_detail_works(
    client: AsyncClient, db_session, courier_account, admin_account
):
    dp = await _courier(db_session, courier_account)
    resp = await client.get(
        f"/api/v1/admin/payouts/couriers/{dp.id}/detail",
        headers=_headers(admin_account),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"]


async def test_standalone_cash_requires_catalog_product(
    client: AsyncClient, db_session, courier_account
):
    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await db_session.commit()
    resp = await client.post(
        "/api/v1/recargas",
        json={"company": "Telcel", "phone": "4121234567", "amount": 50, "payment_method": "cash"},
        headers=_headers(courier_account),
    )
    assert resp.status_code == 400, resp.text
    assert "catálogo" in resp.json()["detail"].lower()

    dp = await _courier(db_session, courier_account)
    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("0.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("0.00")


async def test_standalone_courier_recarga_creates_debt_and_credit(
    client: AsyncClient, db_session, courier_account, monkeypatch
):
    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await db_session.commit()

    async def fake_config(db):
        return sivetel_service.SivetelConfig(
            base_url="https://example.test/ApiWS",
            account="demo",
            user="demo",
            password="demo",
            timeout_seconds=10,
        )

    async def fake_catalog(client):
        return [
            {
                "nombre": "Bait",
                "codigo": "BAIT099",
                "descripcion": "Bait Internet en Casa $99.00",
                "monto": "99.00",
            }
        ]

    monkeypatch.setattr(sivetel_service, "load_config", fake_config)
    monkeypatch.setattr(sivetel_service, "obtener_catalogo", fake_catalog)

    resp = await client.post(
        "/api/v1/recargas",
        json={
            "company": "Bait",
            "phone": "5555555506",
            "amount": 99,
            "payment_method": "cash",
            "product_code": "BAIT099",
        },
        headers=_headers(courier_account),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["origin"] == "courier"
    assert data["product_code"] == "BAIT099"
    assert Decimal(data["amount"]) == Decimal("99.00")
    assert Decimal(data["fee"]) == Decimal("2.00")

    dp = await _courier(db_session, courier_account)
    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("99.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("2.00")


async def test_portal_transfer_requires_catalog_product(
    client: AsyncClient, db_session
):
    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await db_session.commit()
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Recarga", "email": "cliente-rec@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    resp = await client.post(
        "/api/v1/recargas",
        json={
            "company": "Telcel",
            "phone": "4121234567",
            "amount": 50,
            "payment_method": "transfer",
        },
        headers=_headers(token),
    )
    assert resp.status_code == 400, resp.text
    assert "catálogo" in resp.json()["detail"].lower()


async def test_portal_transfer_recarga_creates_request(
    client: AsyncClient, db_session, monkeypatch
):
    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await db_session.commit()
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Portal", "email": "portal-rec@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]

    async def fake_config(db):
        return sivetel_service.SivetelConfig(
            base_url="https://example.test/ApiWS",
            account="demo",
            user="demo",
            password="demo",
            timeout_seconds=10,
        )

    async def fake_catalog(client):
        return [
            {
                "nombre": "Internet Móvil",
                "codigo": "ITM050",
                "descripcion": "Internet Telcel $50",
                "monto": "50.00",
            }
        ]

    monkeypatch.setattr(sivetel_service, "load_config", fake_config)
    monkeypatch.setattr(sivetel_service, "obtener_catalogo", fake_catalog)

    resp = await client.post(
        "/api/v1/recargas",
        json={
            "company": "Telcel",
            "phone": "4121234567",
            "amount": 1,
            "payment_method": "transfer",
            "product_code": "ITM050",
        },
        headers=_headers(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["origin"] == "portal"
    assert data["payment_method"] == "transfer"
    assert data["company"] == "Telcel"
    assert data["product_code"] == "ITM050"
    assert data["product_kind"] == "datos"
    assert Decimal(data["amount"]) == Decimal("50.00")
    assert Decimal(data["fee"]) == Decimal("0.00")
    assert Decimal(data["total"]) == Decimal("50.00")
    assert data["status"] == "requested"


async def test_portal_transfer_validation_marks_recarga_paid(
    client: AsyncClient, db_session, monkeypatch
):
    from app.api.v1 import recargas as recargas_api
    from app.services import bank_service

    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await set_setting(db_session, "CEP_ENABLED", "true")
    await db_session.commit()
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Valida", "email": "valida-rec@test.com", "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    recarga = await recarga_service.create_transfer_recarga(
        db_session,
        user,
        company="Telcel",
        phone="4121234567",
        amount=Decimal("50.00"),
        product_code="ITM050",
        product_description="Internet Telcel $50",
        product_kind="datos",
    )

    async def fake_accounts(db):
        return [{
            "clabe": "012180001234567890",
            "bank_code": "40012",
            "bank_name": "BBVA",
            "holder": "TuPedidoJR",
        }]

    async def fake_validate(**kwargs):
        assert kwargs["amount_cents"] == 5000
        assert kwargs["receiver_account"] == "012180001234567890"
        return {"status": "valid", "tracking_key": kwargs["clave_rastreo"]}

    monkeypatch.setattr(bank_service, "receiver_accounts", fake_accounts)
    monkeypatch.setattr(recargas_api, "validate_transfer", fake_validate)

    resp = await client.post(
        f"/api/v1/recargas/{recarga.id}/validate-transfer",
        json={
            "clave_rastreo": "MBAN010024112600000001",
            "sender_bank": "40002",
        },
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "approved"

    await db_session.refresh(recarga)
    assert recarga.payment_status == "paid"
    assert recarga.status == "pending"
    assert recarga.transfer_tracking_key == "MBAN010024112600000001"
    assert recarga.cep_status == "valid"
    assert recarga.cep_sender_bank == "40002"
    assert recarga.cep_receiver_bank == "40012"
    assert recarga.paid_at is not None


async def test_portal_transfer_receipt_marks_recarga_paid(
    client: AsyncClient, db_session, monkeypatch
):
    from app.api.v1 import recargas as recargas_api
    from app.services import bank_service

    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await set_setting(db_session, "CEP_ENABLED", "true")
    await set_setting(db_session, "RECEIPT_VALIDATION_ENABLED", "true")
    await set_setting(db_session, "RECEIPT_VALIDATION_PROVIDER", "apicep")
    await set_setting(db_session, "APICEP_API_KEY", "test-key")
    await db_session.commit()
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Comprobante",
        "email": "comprobante-rec@test.com",
        "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    recarga = await recarga_service.create_transfer_recarga(
        db_session,
        user,
        company="Telcel",
        phone="4121234567",
        amount=Decimal("50.00"),
        product_code="ITM050",
        product_description="Internet Telcel $50",
        product_kind="datos",
    )

    async def fake_accounts(db):
        return [{
            "clabe": "012180001234567890",
            "bank_code": "40012",
            "bank_name": "BBVA",
            "holder": "TuPedidoJR",
        }]

    async def fake_create(*args, **kwargs):
        return SimpleNamespace(
            status="high",
            extracted={
                "trackingKey": "MBAN010024112600000002",
                "senderBank": "40002",
                "validation": {
                    "cepDetails": {"receiverBank": "40012"}
                },
            },
            issues=[],
            error=None,
            summary="",
        )

    monkeypatch.setattr(bank_service, "receiver_accounts", fake_accounts)
    monkeypatch.setattr(recargas_api, "create_and_validate", fake_create)

    resp = await client.post(
        f"/api/v1/recargas/{recarga.id}/validate-receipt",
        files={"file": ("comprobante.pdf", b"%PDF-1.4 recarga", "application/pdf")},
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "approved"

    await db_session.refresh(recarga)
    assert recarga.payment_status == "paid"
    assert recarga.status == "pending"
    assert recarga.transfer_tracking_key == "MBAN010024112600000002"
    assert recarga.cep_status == "valid"


async def test_courier_can_offer_recarga_on_delivered_order(
    client: AsyncClient, db_session, courier_account
):
    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await db_session.commit()
    dp = await _courier(db_session, courier_account)
    customer = User(
        name="Cliente Recarga",
        email="recarga-order-customer@test.com",
        password_hash="x",
        phone="4120000000",
    )
    db_session.add(customer)
    await db_session.flush()
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Negocio Recarga",
        owner_id=customer.id,
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Calle Prueba",
    )
    db_session.add(restaurant)
    await db_session.flush()
    order = Order(
        id=uuid.uuid4(),
        user_id=customer.id,
        restaurant_id=restaurant.id,
        delivery_person_id=dp.id,
        status="delivered",
        subtotal=Decimal("100.00"),
        delivery_fee=Decimal("10.00"),
        total=Decimal("110.00"),
        delivery_address="Calle Principal 123",
        delivery_location="SRID=4326;POINT(-99.14 19.44)",
        payment_method="cash",
        payment_status="pending",
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/recargas",
        json={
            "company": "Telcel",
            "phone": "4121234567",
            "amount": 50,
            "payment_method": "cash",
            "order_id": str(order.id),
        },
        headers=_headers(courier_account),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["fee"] == "2.00"
    assert data["total"] == "52.00"

    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("50.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("2.00")


async def test_refund_reverses_debt_and_commission(
    client: AsyncClient, db_session, courier_account, admin_account
):
    dp = await _courier(db_session, courier_account)
    recarga = await recarga_service.create_cash_recarga(
        db_session,
        dp,
        company="Telcel",
        phone="4121234567",
        amount=Decimal("100.00"),
    )
    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("100.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("2.00")

    failed = await client.post(
        f"/api/v1/admin/recargas/{recarga.id}/fail",
        json={"refund": True, "error_message": "Sin saldo con el proveedor"},
        headers=_headers(admin_account),
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "refunded"
    assert failed.json()["payment_status"] == "refunded"

    await db_session.refresh(dp)
    assert Decimal(str(dp.pending_platform_debt)) == Decimal("0.00")
    assert Decimal(str(dp.pending_platform_credit)) == Decimal("0.00")


async def test_catalog_shows_intermittency_and_blocks_recarga(
    client: AsyncClient, db_session, monkeypatch
):
    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await db_session.commit()
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Intermitencia",
        "email": "cliente-intermitencia@test.com",
        "password": "pass1234",
    })
    token = resp.json()["access_token"]

    async def fake_config(db):
        return sivetel_service.SivetelConfig(
            base_url="https://example.test/ApiWS",
            account="demo",
            user="demo",
            password="demo",
            timeout_seconds=10,
        )

    async def fake_catalog(client):
        return [
            {
                "nombre": "Bait",
                "codigo": "BAIT099",
                "descripcion": "Bait Internet en Casa $99.00",
                "monto": "99.00",
            }
        ]

    async def fake_status(client):
        return {
            "available": False,
            "message": (
                "El servicio de recargas no está disponible por una "
                "intermitencia. Intenta más tarde."
            ),
        }

    monkeypatch.setattr(sivetel_service, "load_config", fake_config)
    monkeypatch.setattr(sivetel_service, "obtener_catalogo", fake_catalog)
    monkeypatch.setattr(sivetel_service, "provider_status", fake_status)

    catalog = await client.get(
        "/api/v1/recargas/catalogo", headers=_headers(token)
    )
    assert catalog.status_code == 200, catalog.text
    data = catalog.json()
    assert data["provider"]["available"] is False
    assert "intermitencia" in data["provider"]["message"].lower()
    assert data["companies"]

    created = await client.post(
        "/api/v1/recargas",
        json={
            "company": "Bait",
            "phone": "5555555506",
            "amount": 99,
            "payment_method": "transfer",
            "product_code": "BAIT099",
        },
        headers=_headers(token),
    )
    assert created.status_code == 503, created.text
    assert "intermitencia" in created.json()["detail"].lower()


async def test_recarga_ticket_endpoint_and_email(
    client: AsyncClient, db_session, monkeypatch
):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Ticket",
        "email": "cliente-ticket@test.com",
        "password": "pass1234",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(
        User, uuid.UUID(decode_access_token(token)["sub"])
    )
    recarga = await recarga_service.create_transfer_recarga(
        db_session,
        user,
        company="Bait",
        phone="5555555506",
        amount=Decimal("99.00"),
        product_code="BAIT099",
        product_description="Bait Internet en Casa $99.00",
        product_kind="datos",
    )
    recarga.status = "completed"
    recarga.provider_folio = "123456"
    recarga.completed_at = datetime.now(timezone.utc)
    await db_session.commit()
    await db_session.refresh(recarga)

    ticket = await client.get(
        f"/api/v1/recargas/{recarga.id}/ticket", headers=_headers(token)
    )
    assert ticket.status_code == 200, ticket.text
    data = ticket.json()
    assert data["ticket_number"] == f"TPJ-R{str(recarga.id)[:8].upper()}"
    assert data["company"] == "Bait"
    assert data["phone"] == "5555555506"
    assert data["provider_folio"] == "123456"
    assert data["total"] == "99.00"

    other = await client.post("/api/v1/auth/register", json={
        "name": "Otro Cliente",
        "email": "otro-ticket@test.com",
        "password": "pass1234",
    })
    other_token = other.json()["access_token"]
    denied = await client.get(
        f"/api/v1/recargas/{recarga.id}/ticket",
        headers=_headers(other_token),
    )
    assert denied.status_code == 404

    captured = {}

    async def fake_send(db, to, subject, html, text=None, attachments=None):
        captured.update({
            "to": to, "subject": subject, "html": html, "text": text
        })
        return True, "ok"

    monkeypatch.setattr(recarga_ticket_service, "send_email", fake_send)
    sent = await recarga_ticket_service.send_recarga_ticket(db_session, recarga)
    assert sent is True
    assert captured["to"] == "cliente-ticket@test.com"
    assert "Bait" in captured["subject"]
    assert "5555555506" in captured["html"]
    assert "123456" in captured["html"]
    await db_session.refresh(recarga)
    assert recarga.ticket_sent_at is not None
    again = await recarga_ticket_service.send_recarga_ticket(db_session, recarga)
    assert again is False
