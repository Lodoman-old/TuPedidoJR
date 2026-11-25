"""Campañas de cupón a clientes de un negocio."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient

from app.api.v1 import business_coupons
from app.core.security import decode_access_token
from app.models.coupon import Coupon
from app.models.coupon_campaign import CouponCampaign
from app.models.order import Order
from app.models.push_token import PushToken
from app.models.restaurant import Restaurant
from app.models.user import User
from sqlalchemy import func, select


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str, name: str = "Cliente") -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": name,
            "email": email,
            "phone": "4121234567",
            "password": "pass1234",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _restaurant(db_session, owner_token: str) -> Restaurant:
    owner_id = uuid.UUID(decode_access_token(owner_token)["sub"])
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Negocio Campaña",
        slug=f"campana-{uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 1",
        is_open=True,
        status="active",
        public_page_enabled=True,
        delivery_enabled=True,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    await db_session.commit()
    await db_session.refresh(resto)
    return resto


def _coupon(resto: Restaurant, **overrides) -> Coupon:
    data = dict(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        code=f"PROMO{uuid.uuid4().hex[:4].upper()}",
        description="10% en tu próximo pedido",
        discount_type="percentage",
        discount_value=Decimal("10"),
        min_order_amount=Decimal("0"),
        max_uses=0,
        is_active=True,
    )
    data.update(overrides)
    return Coupon(**data)


async def _customer_with_order(db_session, resto: Restaurant, email: str):
    # Create the customer directly to keep the order setup deterministic.
    customer = User(
        id=uuid.uuid4(),
        name="Cliente Campaña",
        email=email,
        phone="4121234567",
        password_hash="x",
        is_active=True,
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add(
        Order(
            id=uuid.uuid4(),
            user_id=customer.id,
            restaurant_id=resto.id,
            status="delivered",
            subtotal=Decimal("50"),
            delivery_fee=Decimal("0"),
            total=Decimal("50"),
            delivery_address="Calle 1",
            delivery_location="SRID=4326;POINT(-100.99 20.64)",
            payment_method="cash",
            payment_status="approved",
            placed_at=datetime.now(timezone.utc),
            delivered_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        PushToken(
            user_id=customer.id,
            token=f"token-{uuid.uuid4().hex}",
            platform="web",
            is_active=True,
        )
    )
    await db_session.commit()
    return customer


async def test_audience_and_campaign_send(
    client, db_session, monkeypatch
):
    owner = await _register(client, "owner-campana@test.com", "Dueño Campaña")
    resto = await _restaurant(db_session, owner)
    coupon = _coupon(resto)
    db_session.add(coupon)
    await db_session.commit()
    await _customer_with_order(db_session, resto, "cliente-campana@test.com")

    calls = {"tokens": 0, "emails": 0}

    async def fake_push(db, tokens, title, body, data, style=None):
        calls["tokens"] += 1
        return {"sent": len(tokens), "failed": 0, "deactivated": 0}

    async def fake_email(
        db,
        to,
        business_name,
        code,
        description,
        discount_label,
        min_order_label,
        valid_until_label,
        link,
    ):
        calls["emails"] += 1
        return True, "ok"

    monkeypatch.setattr(business_coupons, "send_to_tokens", fake_push)
    monkeypatch.setattr(business_coupons, "send_coupon_campaign", fake_email)

    audience = await client.get(
        f"/api/v1/restaurants/{resto.id}/coupons/{coupon.id}/audience",
        headers=_headers(owner),
    )
    assert audience.status_code == 200, audience.text
    data = audience.json()
    assert data["customers"] == 1
    assert data["push_devices"] == 1
    assert data["emails"] == 1
    assert data["can_send"] is True

    sent = await client.post(
        f"/api/v1/restaurants/{resto.id}/coupons/{coupon.id}/campaign",
        headers=_headers(owner),
        json={"channels": ["push", "email"]},
    )
    assert sent.status_code == 200, sent.text
    result = sent.json()
    assert result["push_sent"] == 1
    assert result["email_sent"] == 1
    assert result["audience"] == 1
    assert calls == {"tokens": 1, "emails": 1}

    total = await db_session.scalar(select(func.count()).select_from(CouponCampaign))
    assert total == 1

    blocked = await client.post(
        f"/api/v1/restaurants/{resto.id}/coupons/{coupon.id}/campaign",
        headers=_headers(owner),
        json={"channels": ["email"]},
    )
    assert blocked.status_code == 429

    after = await client.get(
        f"/api/v1/restaurants/{resto.id}/coupons/{coupon.id}/audience",
        headers=_headers(owner),
    )
    assert after.json()["can_send"] is False


async def test_campaign_forbidden_for_other_user(client, db_session):
    owner = await _register(client, "owner-campana2@test.com", "Dueño")
    other = await _register(client, "otro-campana@test.com", "Otro")
    resto = await _restaurant(db_session, owner)
    coupon = _coupon(resto)
    db_session.add(coupon)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/restaurants/{resto.id}/coupons/{coupon.id}/audience",
        headers=_headers(other),
    )
    assert resp.status_code == 403
