"""Recarga de tiempo aire agregada al pedido."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.delivery_person import DeliveryPerson
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.recarga_order import RecargaOrder
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services import sivetel_service
from app.services.setting_service import set_setting


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, name: str, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "pass1234"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _seed(client: AsyncClient, db_session):
    customer = await _register(client, "Cliente Recarga", "recharge-customer@test.com")
    owner = await _register(client, "Dueño Recarga", "recharge-owner@test.com")
    owner_id = uuid.UUID(decode_access_token(owner)["sub"])

    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Negocio Recarga",
        owner_id=owner_id,
        location="SRID=4326;POINT(-99.13 19.43)",
        address="Calle Prueba 20",
        is_open=True,
        delivery_radius_m=5000,
        delivery_fee=Decimal("10.00"),
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        name="Producto Recarga",
        price=Decimal("50.00"),
        preparation_time_min=10,
        is_available=True,
    )
    db_session.add(restaurant)
    db_session.add(item)
    await set_setting(db_session, "RECHARGES_ENABLED", "true")
    await db_session.commit()
    return customer, restaurant, item


def _payload(restaurant: Restaurant, item: MenuItem, **kwargs) -> dict:
    data = {
        "restaurant_id": str(restaurant.id),
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        "delivery_address": "Calle Principal 123",
        "delivery_location": {"lat": 19.44, "lng": -99.14},
        "recharge_company": "Telcel",
        "recharge_phone": "4121234567",
        "recharge_amount": 50,
    }
    data.update(kwargs)
    return data


async def test_estimate_cash_recharge_adds_two_pesos(client, db_session):
    customer, restaurant, item = await _seed(client, db_session)

    without = await client.post(
        "/api/v1/orders/estimate-price",
        json=_payload(restaurant, item, recharge_amount=0),
        headers=_headers(customer),
    )
    assert without.status_code == 200, without.text
    with_recharge = await client.post(
        "/api/v1/orders/estimate-price",
        json=_payload(restaurant, item, payment_method="cash"),
        headers=_headers(customer),
    )
    assert with_recharge.status_code == 200, with_recharge.text

    plain = Decimal(without.json()["total_to_pay"])
    cash = with_recharge.json()
    assert Decimal(cash["recharge_amount"]) == Decimal("50.00")
    assert Decimal(cash["recharge_fee"]) == Decimal("2.00")
    assert Decimal(cash["total_to_pay"]) == plain + Decimal("52.00")


async def test_estimate_transfer_recharge_has_no_fee(client, db_session):
    customer, restaurant, item = await _seed(client, db_session)
    await set_setting(db_session, "TRANSFER_ENABLED", "true")
    await db_session.commit()

    without = await client.post(
        "/api/v1/orders/estimate-price",
        json=_payload(restaurant, item, recharge_amount=0),
        headers=_headers(customer),
    )
    with_recharge = await client.post(
        "/api/v1/orders/estimate-price",
        json=_payload(restaurant, item, payment_method="transfer"),
        headers=_headers(customer),
    )
    assert with_recharge.status_code == 200, with_recharge.text
    data = with_recharge.json()
    assert Decimal(data["recharge_fee"]) == Decimal("0.00")
    assert Decimal(data["total_to_pay"]) == (
        Decimal(without.json()["total_to_pay"]) + Decimal("50.00")
    )


async def test_cash_order_creates_checkout_recharge(
    client, db_session
):
    customer, restaurant, item = await _seed(client, db_session)

    resp = await client.post(
        "/api/v1/orders", json=_payload(restaurant, item), headers=_headers(customer)
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert Decimal(data["recharge_amount"]) == Decimal("50.00")
    assert Decimal(data["recharge_fee"]) == Decimal("2.00")
    assert Decimal(data["total_to_pay"]) == Decimal(data["total"]) + Decimal("52.00")

    recarga = await db_session.scalar(
        select_recarga(data["id"])
    )
    assert recarga is not None
    assert recarga.origin == "checkout"
    assert recarga.payment_method == "cash"
    assert recarga.payment_status == "paid"
    assert recarga.fee == Decimal("2.00")
    assert recarga.debt_applied is True
    assert recarga.credit_applied is True


def select_recarga(order_id):
    from sqlalchemy import select

    return select(RecargaOrder).where(RecargaOrder.order_id == uuid.UUID(order_id))


async def test_order_with_catalog_product_code(client, db_session, monkeypatch):
    customer, restaurant, item = await _seed(client, db_session)

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
        "/api/v1/orders",
        json=_payload(
            restaurant,
            item,
            recharge_amount=0,
            recharge_product_code="BAIT099",
        ),
        headers=_headers(customer),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert Decimal(data["recharge_amount"]) == Decimal("99.00")
    assert data["recharge_company"] == "Bait"
    assert data["recharge_product_code"] == "BAIT099"
    assert data["recharge_product_description"] == "Bait Internet en Casa $99.00"
    assert data["recharge_kind"] == "datos"
    assert Decimal(data["total_to_pay"]) == Decimal(data["total"]) + Decimal("101.00")


async def test_transfer_order_creates_pending_recharge(client, db_session):
    customer, restaurant, item = await _seed(client, db_session)
    await set_setting(db_session, "TRANSFER_ENABLED", "true")
    await db_session.commit()

    resp = await client.post(
        "/api/v1/orders",
        json=_payload(restaurant, item, payment_method="transfer"),
        headers=_headers(customer),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert Decimal(data["recharge_fee"]) == Decimal("0.00")
    assert Decimal(data["total_to_pay"]) == Decimal(data["total"]) + Decimal("50.00")

    recarga = await db_session.scalar(select_recarga(data["id"]))
    assert recarga.payment_method == "transfer"
    assert recarga.payment_status == "pending"


async def test_recharges_can_be_hidden_with_setting(client, db_session):
    customer, restaurant, item = await _seed(client, db_session)
    await set_setting(db_session, "RECHARGES_ENABLED", "false")
    await db_session.commit()

    estimate = await client.post(
        "/api/v1/orders/estimate-price",
        json=_payload(restaurant, item),
        headers=_headers(customer),
    )
    assert estimate.status_code == 200, estimate.text
    assert Decimal(estimate.json()["recharge_amount"]) == Decimal("0.00")
    assert Decimal(estimate.json()["total_to_pay"]) == Decimal(estimate.json()["total"])

    blocked = await client.post(
        "/api/v1/orders", json=_payload(restaurant, item), headers=_headers(customer)
    )
    assert blocked.status_code == 400
    assert "no están disponibles" in blocked.json()["detail"].lower()

    config = await client.get("/api/v1/payments/config")
    assert config.status_code == 200
    assert config.json()["recharges_enabled"] is False


async def test_pickup_and_small_recharge_are_rejected(client, db_session):
    customer, restaurant, item = await _seed(client, db_session)
    restaurant.pickup_enabled = True
    await db_session.commit()

    pickup = await client.post(
        "/api/v1/orders",
        json=_payload(restaurant, item, fulfillment_type="pickup"),
        headers=_headers(customer),
    )
    assert pickup.status_code == 400
    assert "entrega a domicilio" in pickup.json()["detail"].lower()

    small = await client.post(
        "/api/v1/orders",
        json=_payload(restaurant, item, recharge_amount=5),
        headers=_headers(customer),
    )
    assert small.status_code == 400
    assert "mínima" in small.json()["detail"].lower()


async def test_cancelling_cash_order_charges_recharge_to_balance(
    client, db_session
):
    customer, restaurant, item = await _seed(client, db_session)
    created = await client.post(
        "/api/v1/orders", json=_payload(restaurant, item), headers=_headers(customer)
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    cancelled = await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        json={"reason": "Prueba"},
        headers=_headers(customer),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["recharge_status"] == "charged"

    user = await db_session.get(
        User, uuid.UUID(decode_access_token(customer)["sub"])
    )
    await db_session.refresh(user)
    assert Decimal(str(user.pending_balance)) == Decimal("50.00")


async def test_cash_delivery_adds_recharge_to_courier_debt(
    client, db_session
):
    customer, restaurant, item = await _seed(client, db_session)
    courier_token = await _register(client, "Repartidor Recarga", "recharge-courier@test.com")
    courier_id = uuid.UUID(decode_access_token(courier_token)["sub"])
    dp = DeliveryPerson(user_id=courier_id, vehicle_type="motorcycle", is_available=True)
    db_session.add(dp)
    await db_session.commit()
    await db_session.refresh(dp)

    created = await client.post(
        "/api/v1/orders", json=_payload(restaurant, item), headers=_headers(customer)
    )
    assert created.status_code == 201, created.text
    order = await db_session.get(Order, uuid.UUID(created.json()["id"]))
    order.delivery_person_id = dp.id
    order.status = "picked_up"
    await db_session.commit()

    delivered = await client.post(
        f"/api/v1/delivery/deliver/{order.id}", headers=_headers(courier_token)
    )
    assert delivered.status_code == 200, delivered.text

    await db_session.refresh(dp)
    expected = (
        (order.total or Decimal("0"))
        + (order.recharge_total or Decimal("0"))
        - (order.delivery_earnings or Decimal("0"))
    )
    assert Decimal(str(dp.pending_platform_debt)) == expected

    recarga = await db_session.scalar(select_recarga(str(order.id)))
    assert recarga.delivery_person_id == dp.id


async def _superuser(client, db_session, email: str) -> str:
    token = await _register(client, "Admin Recarga", email)
    user = await db_session.get(
        User, uuid.UUID(decode_access_token(token)["sub"])
    )
    user.is_superuser = True
    await db_session.commit()
    return token


async def _transfer_order(client, db_session):
    customer, restaurant, item = await _seed(client, db_session)
    await set_setting(db_session, "TRANSFER_ENABLED", "true")
    await db_session.commit()
    resp = await client.post(
        "/api/v1/orders",
        json=_payload(restaurant, item, payment_method="transfer"),
        headers=_headers(customer),
    )
    assert resp.status_code == 201, resp.text
    return customer, resp.json()


async def test_transfer_approval_marks_recharge_paid(client, db_session):
    customer, order = await _transfer_order(client, db_session)
    admin = await _superuser(client, db_session, "recharge-admin@test.com")

    confirmed = await client.post(
        f"/api/v1/admin/payouts/transfers/{order['id']}/confirm",
        headers=_headers(admin),
    )
    assert confirmed.status_code == 200, confirmed.text

    recarga = await db_session.scalar(select_recarga(order["id"]))
    await db_session.refresh(recarga)
    assert recarga.payment_status == "paid"


async def test_transfer_cancelled_before_payment_cancels_recharge(
    client, db_session
):
    customer, order = await _transfer_order(client, db_session)

    cancelled = await client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        json={"reason": "Prueba"},
        headers=_headers(customer),
    )
    assert cancelled.status_code == 200, cancelled.text

    recarga = await db_session.scalar(select_recarga(order["id"]))
    await db_session.refresh(recarga)
    assert recarga.status == "cancelled"
    assert recarga.payment_status == "cancelled"

    user = await db_session.get(
        User, uuid.UUID(decode_access_token(customer)["sub"])
    )
    await db_session.refresh(user)
    assert Decimal(str(user.pending_balance)) == Decimal("0")


async def test_transfer_cancelled_after_payment_refunds_only_order(
    client, db_session
):
    customer, order = await _transfer_order(client, db_session)
    admin = await _superuser(client, db_session, "recharge-admin2@test.com")
    await client.post(
        f"/api/v1/admin/payouts/transfers/{order['id']}/confirm",
        headers=_headers(admin),
    )

    cancelled = await client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        json={"reason": "Prueba"},
        headers=_headers(customer),
    )
    assert cancelled.status_code == 200, cancelled.text
    data = cancelled.json()
    assert Decimal(data["refund_amount"]) == Decimal(order["total"])
    assert Decimal(data["total_to_pay"]) == Decimal(data["total"]) + Decimal("50.00")
    assert data["recharge_status"] == "retained"

    recarga = await db_session.scalar(select_recarga(order["id"]))
    await db_session.refresh(recarga)
    assert recarga.payment_status == "paid"
