"""Tests for opening hours, cancellations, settings and reports."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.user import User

TZ = ZoneInfo("America/Mexico_City")


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Owner Biz", "email": "owner-biz@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Customer Biz", "email": "customer-biz@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Biz", "email": "admin-biz@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    from app.core.security import decode_access_token
    payload = decode_access_token(token)
    user = await db_session.get(User, uuid.UUID(payload["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


@pytest.fixture
async def restaurant(db_session, owner_token):
    from app.core.security import decode_access_token
    payload = decode_access_token(owner_token)

    rid = uuid.uuid4()
    resto = Restaurant(
        id=rid, name="Horario Resto", owner_id=payload["sub"],
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 5 de Mayo 209", is_open=True, rating=4.5,
        delivery_radius_m=5000, delivery_fee=20.00,
        affiliation_expires_at=date.today() + timedelta(days=365),
    )
    db_session.add(resto)
    item = MenuItem(
        id=uuid.uuid4(), restaurant_id=rid, name="Taco",
        price=30.00, preparation_time_min=5, is_available=True,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(resto)
    await db_session.refresh(item)
    return resto, item


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _entry(day: int, open_time: str = "00:00", close_time: str = "23:59") -> dict:
    return {
        "day_of_week": day,
        "open_time": open_time,
        "close_time": close_time,
        "is_closed": False,
    }


async def _create_order(client, token, restaurant, item, payment_method="cash", tip_amount=0, option_ids=None, points_to_redeem=0):
    resp = await client.post(
        "/api/v1/orders",
        json={
            "restaurant_id": str(restaurant.id),
            "items": [{
                "menu_item_id": str(item.id),
                "quantity": 1,
                "option_ids": option_ids or [],
            }],
            "delivery_address": "Calle 5 de Mayo 209",
            "delivery_location": {"lat": 20.6449, "lng": -100.9945},
            "payment_method": payment_method,
            "tip_amount": tip_amount,
            "points_to_redeem": points_to_redeem,
        },
        headers=_headers(token),
    )
    return resp


class TestOpeningHours:
    async def test_fallback_to_manual_switch(self, client, restaurant):
        resto, _ = restaurant
        resp = await client.get(f"/api/v1/restaurants/{resto.id}/open-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_schedule"] is False
        assert data["is_open_now"] is True

    async def test_closed_schedule_blocks_order(
        self, client, restaurant, owner_token, customer_token,
    ):
        resto, item = restaurant
        weekday = datetime.now(TZ).weekday()
        entries = []
        for day in range(7):
            if day == weekday:
                entries.append(_entry(day, "00:00", "00:01"))
            else:
                entries.append(_entry(day))

        resp = await client.put(
            f"/api/v1/restaurants/{resto.id}/schedule",
            json={"entries": entries},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200

        status = await client.get(f"/api/v1/restaurants/{resto.id}/open-status")
        assert status.json()["is_open_now"] is False

        order = await _create_order(client, customer_token, resto, item)
        assert order.status_code == 409
        assert "cerrado" in order.json()["detail"].lower() or "Cerrado" in order.json()["detail"]

    async def test_open_schedule_allows_order(
        self, client, restaurant, owner_token, customer_token,
    ):
        resto, item = restaurant
        resp = await client.put(
            f"/api/v1/restaurants/{resto.id}/schedule",
            json={"entries": [_entry(day) for day in range(7)]},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200

        status = await client.get(f"/api/v1/restaurants/{resto.id}/open-status")
        assert status.json()["is_open_now"] is True

        order = await _create_order(client, customer_token, resto, item)
        assert order.status_code == 201

    async def test_schedule_requires_owner(
        self, client, restaurant, customer_token,
    ):
        resto, _ = restaurant
        resp = await client.get(
            f"/api/v1/restaurants/{resto.id}/schedule",
            headers=_headers(customer_token),
        )
        assert resp.status_code == 403

    async def test_manual_switch_overrides_schedule(
        self, client, restaurant, owner_token, db_session,
    ):
        resto, _ = restaurant
        await client.put(
            f"/api/v1/restaurants/{resto.id}/schedule",
            json={"entries": [_entry(day) for day in range(7)]},
            headers=_headers(owner_token),
        )
        resto.is_open = False
        await db_session.commit()

        status = await client.get(f"/api/v1/restaurants/{resto.id}/open-status")
        assert status.json()["is_open_now"] is False


def test_overnight_shift_is_open():
    from datetime import time as clock
    from types import SimpleNamespace

    from app.services.schedule_service import _evaluate

    friday_shift = SimpleNamespace(
        day_of_week=4, is_closed=False,
        open_time=clock(20, 0), close_time=clock(2, 0),
    )
    # Friday 23:00 and Saturday 01:00 belong to the same shift.
    assert _evaluate([friday_shift], datetime(2026, 11, 6, 23, 0))["is_open"] is True
    assert _evaluate([friday_shift], datetime(2026, 11, 7, 1, 0))["is_open"] is True
    assert _evaluate([friday_shift], datetime(2026, 11, 6, 12, 0))["is_open"] is False


def test_next_open_message():
    from datetime import time as clock
    from types import SimpleNamespace

    from app.services.schedule_service import _evaluate

    monday_only = SimpleNamespace(
        day_of_week=0, is_closed=False,
        open_time=clock(9, 0), close_time=clock(18, 0),
    )
    # Tuesday -> next opening is next Monday.
    state = _evaluate([monday_only], datetime(2026, 11, 3, 12, 0))
    assert state["is_open"] is False
    assert state["next_open"] == clock(9, 0)
    assert state["next_open_offset"] == 6


class TestSearchAndCuisine:
    async def test_search_by_cuisine(
        self, client, restaurant, owner_token, db_session,
    ):
        resto, _ = restaurant
        from app.core.security import decode_access_token
        owner_id = decode_access_token(owner_token)["sub"]
        db_session.add(Restaurant(
            name="Tokyo Roll", cuisine="Sushi", owner_id=owner_id,
            location="SRID=4326;POINT(-100.99 20.64)",
            address="Otra calle", is_open=True, rating=4.8,
            delivery_radius_m=5000, delivery_fee=15.00,
            affiliation_expires_at=date.today() + timedelta(days=365),
        ))
        await db_session.commit()

        resp = await client.get("/api/v1/restaurants", params={"q": "sushi"})
        assert resp.status_code == 200
        names = [row["name"] for row in resp.json()]
        assert "Tokyo Roll" in names

    async def test_search_by_menu_item(
        self, client, restaurant, db_session,
    ):
        resto, _ = restaurant
        from app.models.menu_item import MenuItem
        import uuid as uuid_module

        db_session.add(MenuItem(
            id=uuid_module.uuid4(), restaurant_id=resto.id,
            name="Ramen Tonkotsu", price=120, is_available=True,
        ))
        await db_session.commit()

        resp = await client.get("/api/v1/restaurants", params={"q": "ramen"})
        assert resp.status_code == 200
        assert [row["name"] for row in resp.json()] == ["Horario Resto"]

    async def test_update_cuisine(
        self, client, restaurant, owner_token, customer_token,
    ):
        resto, _ = restaurant
        resp = await client.patch(
            f"/api/v1/restaurants/{resto.id}/profile",
            json={"cuisine": "Pizza", "description": "Pizzas al horno"},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["cuisine"] == "Pizza"

        forbidden = await client.patch(
            f"/api/v1/restaurants/{resto.id}/profile",
            json={"cuisine": "Hack"},
            headers=_headers(customer_token),
        )
        assert forbidden.status_code == 403


class TestSavedAddressCoordinates:
    async def test_address_returns_lat_lng(self, client, customer_token):
        payload = {
            "name": "Casa",
            "address": "Calle 5 de Mayo 209, Centro, C.P. 38240",
            "location": {"lat": 20.6448949, "lng": -100.994575},
            "is_default": True,
            "notes": None,
        }
        created = await client.post(
            "/api/v1/profile/addresses", json=payload, headers=_headers(customer_token),
        )
        assert created.status_code == 201
        assert created.json()["location"]["lat"] == 20.6448949

        listing = await client.get(
            "/api/v1/profile/addresses", headers=_headers(customer_token),
        )
        assert listing.status_code == 200
        assert listing.json()[0]["location"]["lng"] == -100.994575


class TestTransferPayments:
    async def test_transfer_enabled_allows_order(
        self, client, restaurant, customer_token, db_session,
    ):
        from app.models.setting import Setting

        resto, item = restaurant
        db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
        await db_session.commit()

        config = await client.get("/api/v1/payments/config")
        assert config.json()["transfer_enabled"] is True

        order = await _create_order(
            client, customer_token, resto, item, payment_method="transfer",
        )
        assert order.status_code == 201
        assert order.json()["payment_method"] == "transfer"
        assert order.json()["payment_status"] == "pending"

    async def test_mp_stays_disabled(
        self, client, restaurant, customer_token, db_session,
    ):
        from app.models.setting import Setting

        resto, item = restaurant
        db_session.add(Setting(key="MP_ENABLED", value="false"))
        await db_session.commit()

        order = await _create_order(
            client, customer_token, resto, item, payment_method="mp",
        )
        assert order.status_code == 400


class TestTransferSettlement:
    async def test_pending_transfer_is_not_payable_until_confirmed(
        self, client, restaurant, owner_token, db_session,
    ):
        from app.core.security import decode_access_token
        from app.models.order import Order

        resto, _item = restaurant
        owner_id = decode_access_token(owner_token)["sub"]
        order = Order(
            user_id=owner_id,
            restaurant_id=resto.id,
            status="delivered",
            subtotal=100,
            delivery_fee=20,
            total=125,
            delivery_address="Calle 1",
            # Placeholder location; this test only checks the settlement rule.
            delivery_location="SRID=4326;POINT(-100.99 20.64)",
            platform_commission=15,
            delivery_earnings=20,
            payment_method="transfer",
            payment_status="pending",
        )
        db_session.add(order)
        await db_session.commit()

        headers = _headers(owner_token)
        resp = await client.get(f"/api/v1/restaurants/{resto.id}/earnings", headers=headers)
        data = resp.json()
        assert float(data["available_for_payout"]) == 0.0
        assert float(data["pending_confirmation"]) == 85.0

        pending = await client.post(
            f"/api/v1/restaurants/{resto.id}/request-payout", headers=headers,
        )
        assert pending.status_code == 400

        order.payment_status = "approved"
        await db_session.commit()

        resp = await client.get(f"/api/v1/restaurants/{resto.id}/earnings", headers=headers)
        data = resp.json()
        assert float(data["available_for_payout"]) == 85.0
        assert float(data["pending_confirmation"]) == 0.0
        assert float(data["total_collected_transfer"]) == 125.0


class TestAdminPayouts:
    async def test_requires_superuser(self, client, customer_token):
        resp = await client.get(
            "/api/v1/admin/payouts", headers=_headers(customer_token),
        )
        assert resp.status_code == 403

    async def test_returns_restaurants_and_couriers(self, client, superuser_token):
        resp = await client.get(
            "/api/v1/admin/payouts", headers=_headers(superuser_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "restaurants" in data
        assert "couriers" in data

    async def test_audit_records_admin_actions(self, client, superuser_token):
        headers = _headers(superuser_token)
        await client.patch(
            "/api/v1/settings",
            json={"values": {"APP_FLAT_USAGE_FEE": "5"}},
            headers=headers,
        )
        audit = await client.get("/api/v1/admin/audit", headers=headers)
        assert audit.status_code == 200
        assert any(row["action"] == "settings.update" for row in audit.json())

    async def test_courier_locations_api(self, client, customer_token, superuser_token):
        denied = await client.get(
            "/api/v1/admin/couriers/locations", headers=_headers(customer_token),
        )
        assert denied.status_code == 403
        allowed = await client.get(
            "/api/v1/admin/couriers/locations", headers=_headers(superuser_token),
        )
        assert allowed.status_code == 200
        assert isinstance(allowed.json(), list)

    async def test_dashboard_requires_superuser(self, client, customer_token, superuser_token):
        denied = await client.get("/api/v1/admin/dashboard", headers=_headers(customer_token))
        assert denied.status_code == 403
        allowed = await client.get("/api/v1/admin/dashboard", headers=_headers(superuser_token))
        assert allowed.status_code == 200
        data = allowed.json()
        assert "active" in data and "alerts" in data and "recent_orders" in data

    async def test_generate_and_mark_paid(
        self, client, restaurant, superuser_token, db_session,
    ):
        from app.core.security import decode_access_token
        from app.models.order import Order

        resto, _item = restaurant
        user_id = decode_access_token(superuser_token)["sub"]
        db_session.add(Order(
            user_id=user_id,
            restaurant_id=resto.id,
            status="delivered",
            subtotal=100,
            delivery_fee=20,
            total=125,
            delivery_address="Calle 1",
            delivery_location="SRID=4326;POINT(-100.99 20.64)",
            platform_commission=15,
            delivery_earnings=20,
            payment_method="cash",
        ))
        await db_session.commit()

        headers = _headers(superuser_token)
        generated = await client.post(
            f"/api/v1/admin/payouts/restaurants/{resto.id}", headers=headers,
        )
        assert generated.status_code == 200
        assert float(generated.json()["amount"]) == 85.0

        paid = await client.post(
            f"/api/v1/admin/payouts/restaurant/{generated.json()['id']}/mark-paid",
            headers=headers,
        )
        assert paid.status_code == 200
        assert paid.json()["status"] == "paid"

    async def test_reconciliation_by_date_range(
        self, client, restaurant, superuser_token, db_session,
    ):
        from app.core.security import decode_access_token
        from app.models.order import Order
        from datetime import timezone

        resto, _item = restaurant
        user_id = decode_access_token(superuser_token)["sub"]
        db_session.add(Order(
            user_id=user_id,
            restaurant_id=resto.id,
            status="delivered",
            subtotal=200,
            delivery_fee=20,
            total=235,
            delivery_address="Calle 1",
            delivery_location="SRID=4326;POINT(-100.99 20.64)",
            platform_commission=6,
            flat_usage_fee=5,
            tip_amount=10,
            restaurant_owes_platform=11,
            delivery_earnings=30,
            payment_method="cash",
            delivered_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        today = datetime.now(timezone.utc).date().isoformat()
        resp = await client.get(
            f"/api/v1/admin/payouts/reconciliation?start_date={today}&end_date={today}",
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        row = next(r for r in data["restaurants"] if r["name"] == resto.name)
        assert row["orders"] == 1
        assert float(row["subtotal"]) == 200.0
        assert float(row["commission"]) == 6.0
        assert float(row["flat_fee"]) == 5.0
        assert float(row["restaurant_owes"]) == 11.0
        assert float(data["totals"]["total"]) >= 235.0

        denied = await client.get(
            "/api/v1/admin/payouts/reconciliation",
            headers=_headers(superuser_token),
            params={"start_date": today, "end_date": "2000-01-01"},
        )
        assert denied.status_code == 400

    async def test_commission_override_applies_to_new_orders(
        self, client, restaurant, customer_token, superuser_token, db_session,
    ):
        resto, item = restaurant
        resp = await client.patch(
            f"/api/v1/restaurants/{resto.id}/commission",
            json={"commission_percentage": 10},
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 200

        order = await _create_order(client, customer_token, resto, item)
        assert order.status_code == 201
        # Ahora el cobro es una cuota fija, no un porcentaje.
        assert float(order.json()["platform_commission"]) == 5.0

    async def test_commission_can_be_overridden_and_cleared(
        self, client, restaurant, superuser_token, db_session,
    ):
        resto, _item = restaurant
        resp = await client.patch(
            f"/api/v1/restaurants/{resto.id}/commission",
            json={"commission_percentage": 10, "payout_frequency_days": 15},
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 200
        await db_session.refresh(resto)
        assert float(resto.commission_percentage) == 10.0
        assert resto.payout_frequency_days == 15

        resp = await client.patch(
            f"/api/v1/restaurants/{resto.id}/commission",
            json={"commission_percentage": None},
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 200
        await db_session.refresh(resto)
        assert resto.commission_percentage is None


class TestCourierPerformance:
    async def test_bonus_is_applied_and_top_couriers_report(
        self, client, restaurant, customer_token, superuser_token, db_session,
    ):
        from app.core.security import decode_access_token
        from app.models.delivery_person import DeliveryPerson
        from app.models.order import Order

        resto, _item = restaurant
        delivery_token = (await client.post("/api/v1/auth/register", json={
            "name": "Courier Bonus", "email": "courier-bonus@test.com",
            "password": "pass123",
        })).json()["access_token"]
        courier_user = decode_access_token(delivery_token)["sub"]
        customer_id = decode_access_token(customer_token)["sub"]

        courier = DeliveryPerson(
            user_id=courier_user, vehicle_type="motorcycle",
            is_available=True, rating=4.8, total_deliveries=0,
            delivery_bonus_per_order=Decimal("5"),
        )
        db_session.add(courier)
        order = Order(
            user_id=customer_id,
            restaurant_id=resto.id,
            status="ready",
            subtotal=100,
            delivery_fee=20,
            total=125,
            delivery_address="Calle 1",
            delivery_location="SRID=4326;POINT(-100.99 20.64)",
            delivery_earnings=20,
            platform_commission=15,
            flat_usage_fee=5,
            payment_method="cash",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        accepted = await client.post(
            f"/api/v1/delivery/accept/{order.id}",
            headers=_headers(delivery_token),
        )
        assert accepted.status_code == 200
        assert float(accepted.json()["delivery_earnings"]) == 25.0

        # Mark it delivered so the performance report includes it.
        order.status = "delivered"
        order.delivery_person_id = courier.id
        await db_session.commit()

        report = await client.get(
            "/api/v1/reports/summary", headers=_headers(superuser_token),
        )
        assert report.status_code == 200
        couriers = report.json()["top_couriers"]
        assert any(row["name"] == "Courier Bonus" for row in couriers)


    async def test_admin_confirms_pending_transfer(
        self, client, restaurant, customer_token, superuser_token, db_session,
    ):
        from app.models.setting import Setting

        resto, item = restaurant
        db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
        await db_session.commit()
        order = await _create_order(
            client, customer_token, resto, item, payment_method="transfer",
        )
        assert order.status_code == 201
        order_id = order.json()["id"]

        headers = _headers(superuser_token)
        before = await client.get("/api/v1/admin/payouts", headers=headers)
        assert any(t["id"] == order_id for t in before.json()["pending_transfers"])

        confirmed = await client.post(
            f"/api/v1/admin/payouts/transfers/{order_id}/confirm",
            headers=headers,
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["payment_status"] == "approved"

        after = await client.get("/api/v1/admin/payouts", headers=headers)
        assert all(t["id"] != order_id for t in after.json()["pending_transfers"])


class TestCashAdvances:
    async def _courier(self, client, db_session, email):
        from app.core.security import decode_access_token
        from app.models.delivery_person import DeliveryPerson

        token = (await client.post("/api/v1/auth/register", json={
            "name": "Courier Advance", "email": email, "password": "pass123",
        })).json()["access_token"]
        dp = DeliveryPerson(
            user_id=decode_access_token(token)["sub"],
            vehicle_type="motorcycle", is_available=True, rating=4.5,
        )
        db_session.add(dp)
        await db_session.commit()
        await db_session.refresh(dp)
        return token, dp

    async def _order(self, db_session, restaurant_id, customer_id, dp, earnings=20):
        from app.models.order import Order

        order = Order(
            user_id=customer_id,
            restaurant_id=restaurant_id,
            delivery_person_id=dp.id,
            status="in_delivery",
            subtotal=30,
            delivery_fee=20,
            total=55,
            delivery_address="Calle 1",
            delivery_location="SRID=4326;POINT(-100.99 20.64)",
            platform_commission=4.5,
            delivery_earnings=earnings,
            payment_method="transfer",
            payment_status="approved",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)
        return order

    async def test_restaurant_payment_advance_excludes_restaurant_payout(
        self, client, restaurant, customer_token, superuser_token, db_session,
    ):
        from app.core.security import decode_access_token
        from app.models.cash_advance import CashAdvance

        resto, _item = restaurant
        customer_id = decode_access_token(customer_token)["sub"]
        token, dp = await self._courier(client, db_session, "courier-adv-1@test.com")
        order = await self._order(db_session, resto.id, customer_id, dp)

        created = await client.post(
            "/api/v1/delivery/advances",
            json={"order_id": str(order.id)},
            headers=_headers(token),
        )
        assert created.status_code == 201
        assert float(created.json()["amount"]) == 25.5
        advance_id = created.json()["id"]

        approved = await client.post(
            f"/api/v1/admin/advances/{advance_id}/approve",
            json={"pays_restaurant": True},
            headers=_headers(superuser_token),
        )
        assert approved.status_code == 200
        await db_session.refresh(order)
        assert order.restaurant_paid_with_advance is True

        await client.post(f"/api/v1/delivery/pickup/{order.id}", headers=_headers(token))
        await client.post(f"/api/v1/delivery/deliver/{order.id}", headers=_headers(token))

        earnings = await client.get(
            f"/api/v1/restaurants/{resto.id}/earnings",
            headers=_headers(superuser_token),
        )
        assert float(earnings.json()["available_for_payout"]) == 0.0

        advance = await db_session.get(CashAdvance, uuid.UUID(advance_id))
        await db_session.refresh(advance)
        assert advance.status == "settled"
        assert advance.settlement_method == "restaurant_payment"

    async def test_loan_advance_is_deducted_from_courier_payout(
        self, client, restaurant, customer_token, superuser_token, db_session,
    ):
        from app.core.security import decode_access_token
        from app.models.cash_advance import CashAdvance

        resto, _item = restaurant
        customer_id = decode_access_token(customer_token)["sub"]
        token, dp = await self._courier(client, db_session, "courier-adv-2@test.com")
        order = await self._order(db_session, resto.id, customer_id, dp, earnings=200)

        created = await client.post(
            "/api/v1/delivery/advances",
            json={"order_id": str(order.id)},
            headers=_headers(token),
        )
        advance_id = created.json()["id"]
        approved = await client.post(
            f"/api/v1/admin/advances/{advance_id}/approve",
            json={"pays_restaurant": False},
            headers=_headers(superuser_token),
        )
        assert approved.status_code == 200

        await client.post(f"/api/v1/delivery/pickup/{order.id}", headers=_headers(token))
        await client.post(f"/api/v1/delivery/deliver/{order.id}", headers=_headers(token))

        payouts = await client.get(
            "/api/v1/admin/payouts", headers=_headers(superuser_token),
        )
        courier = next(c for c in payouts.json()["couriers"] if c["id"] == str(dp.id))
        assert float(courier["pending_advances"]) == 25.5
        assert float(courier["pending_amount"]) == 174.5

        generated = await client.post(
            f"/api/v1/admin/payouts/couriers/{dp.id}",
            headers=_headers(superuser_token),
        )
        assert generated.status_code == 200
        assert float(generated.json()["amount"]) == 174.5

        advance = await db_session.get(CashAdvance, uuid.UUID(advance_id))
        await db_session.refresh(advance)
        assert advance.status == "settled"
        assert advance.settlement_method == "payout"


class TestShoppingExperience:
    async def test_tip_is_added_to_total_and_courier_earnings(
        self, client, restaurant, customer_token,
    ):
        resto, item = restaurant
        order = await _create_order(
            client, customer_token, resto, item, tip_amount=5,
        )
        assert order.status_code == 201
        data = order.json()
        assert float(data["tip_amount"]) == 5.0
        assert float(data["delivery_earnings"]) == float(data["delivery_fee"]) + 5.0
        assert float(data["total"]) == (
            float(data["subtotal"])
            + float(data["delivery_fee"])
            + float(data["flat_usage_fee"])
            + 5.0
        )

    async def test_public_page_and_availability(
        self, client, restaurant, owner_token, db_session,
    ):
        resto, item = restaurant
        profile = await client.patch(
            f"/api/v1/restaurants/{resto.id}/profile",
            json={"public_page_enabled": True},
            headers=_headers(owner_token),
        )
        assert profile.status_code == 200
        slug = profile.json()["slug"]
        assert slug

        public = await client.get(f"/api/v1/restaurants/public/{slug}")
        assert public.status_code == 200
        assert public.json()["id"] == str(resto.id)

        hidden = await client.patch(
            f"/api/v1/restaurants/{resto.id}/profile",
            json={"public_page_enabled": False},
            headers=_headers(owner_token),
        )
        assert hidden.status_code == 200
        assert (await client.get(f"/api/v1/restaurants/public/{slug}")).status_code == 404

        toggle = await client.patch(
            f"/api/v1/restaurants/{resto.id}/menu/{item.id}/availability",
            json={"is_available": False},
            headers=_headers(owner_token),
        )
        assert toggle.status_code == 200
        assert toggle.json()["is_available"] is False

    async def test_scheduled_order_window(
        self, client, restaurant, customer_token,
    ):
        resto, item = restaurant
        future = (datetime.now(ZoneInfo("UTC")) + timedelta(hours=2)).isoformat()
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Calle 5 de Mayo 209",
                "delivery_location": {"lat": 20.6449, "lng": -100.9945},
                "payment_method": "cash",
                "scheduled_for": future,
            },
            headers=_headers(customer_token),
        )
        assert resp.status_code == 201
        assert resp.json()["scheduled_for"] is not None

        too_soon = (datetime.now(ZoneInfo("UTC")) + timedelta(minutes=2)).isoformat()
        resp = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": "Calle 5 de Mayo 209",
                "delivery_location": {"lat": 20.6449, "lng": -100.9945},
                "payment_method": "cash",
                "scheduled_for": too_soon,
            },
            headers=_headers(customer_token),
        )
        assert resp.status_code == 400

    async def test_public_html_page(self, client, restaurant, owner_token):
        resto, _item = restaurant
        profile = await client.patch(
            f"/api/v1/restaurants/{resto.id}/profile",
            json={"public_page_enabled": True},
            headers=_headers(owner_token),
        )
        slug = profile.json()["slug"]
        page = await client.get(f"/r/{slug}")
        assert page.status_code == 200
        assert "TuPedidoJR" in page.text
        assert resto.name in page.text

    async def test_restaurant_sort_and_filters(
        self, client, restaurant, db_session,
    ):
        resto, _item = restaurant
        resp = await client.get("/api/v1/restaurants", params={"sort": "rating"})
        assert resp.status_code == 200
        ratings = [float(row["rating"]) for row in resp.json()]
        assert ratings == sorted(ratings, reverse=True)

        resp = await client.get(
            "/api/v1/restaurants",
            params={"free_delivery": "true"},
        )
        assert resp.status_code == 200
        assert all(float(row["delivery_fee"]) == 0 for row in resp.json())


class TestOwnDelivery:
    async def test_cash_and_transfer_settlement(
        self, client, restaurant, owner_token, customer_token, db_session,
    ):
        from app.models.order import Order

        resto, item = restaurant
        profile = await client.patch(
            f"/api/v1/restaurants/{resto.id}/profile",
            json={"delivery_mode": "own"},
            headers=_headers(owner_token),
        )
        assert profile.status_code == 200
        assert profile.json()["delivery_mode"] == "own"

        cash_order = await _create_order(
            client, customer_token, resto, item, payment_method="cash",
        )
        assert cash_order.status_code == 201
        cash_data = cash_order.json()
        assert cash_data["delivery_mode"] == "own"
        assert float(cash_data["delivery_earnings"]) == 0.0
        assert float(cash_data["delivery_fee"]) == 20.0

        await client.patch(
            f"/api/v1/restaurants/{resto.id}/orders/{cash_data['id']}/status",
            json={"status": "delivered"},
            headers=_headers(owner_token),
        )

        earnings = await client.get(
            f"/api/v1/restaurants/{resto.id}/earnings",
            headers=_headers(owner_token),
        )
        data = earnings.json()
        assert float(data["available_for_payout"]) == 0.0
        assert float(data["restaurant_debt"]) == 10.0

        from app.models.setting import Setting
        db_session.add(Setting(key="TRANSFER_ENABLED", value="true"))
        await db_session.commit()
        transfer_order = await _create_order(
            client, customer_token, resto, item, payment_method="transfer",
        )
        assert transfer_order.status_code == 201
        await client.patch(
            f"/api/v1/restaurants/{resto.id}/orders/{transfer_order.json()['id']}/status",
            json={"status": "delivered"},
            headers=_headers(owner_token),
        )
        from sqlalchemy import text
        await db_session.execute(
            text("UPDATE orders SET payment_status='approved' WHERE id=:id"),
            {"id": transfer_order.json()["id"]},
        )
        await db_session.commit()

        earnings = await client.get(
            f"/api/v1/restaurants/{resto.id}/earnings",
            headers=_headers(owner_token),
        )
        data = earnings.json()
        # Transfer: 30.00 subtotal - 5.00 cuota fija + 20 own delivery = 45
        # minus 10.00 cash debt = 35.00 payable.
        assert float(data["available_for_payout"]) == 35.0
        assert float(data["restaurant_debt"]) == 10.0


class TestMenuModifiers:
    async def test_required_options_and_price_delta(
        self, client, restaurant, owner_token, customer_token,
    ):
        resto, item = restaurant
        payload = {
            "groups": [
                {
                    "name": "Extras", "selection_type": "multiple",
                    "is_required": False, "min_selections": 0, "max_selections": 2,
                    "sort_order": 1,
                    "options": [
                        {"name": "Queso extra", "price_delta": 5, "sort_order": 1},
                    ],
                },
                {
                    "name": "Tamaño", "selection_type": "single",
                    "is_required": True, "min_selections": 1, "max_selections": 1,
                    "sort_order": 2,
                    "options": [
                        {"name": "Grande", "price_delta": 10, "sort_order": 1},
                    ],
                },
            ]
        }
        created = await client.put(
            f"/api/v1/restaurants/{resto.id}/menu/{item.id}/options",
            json=payload,
            headers=_headers(owner_token),
        )
        assert created.status_code == 200
        groups = created.json()
        assert len(groups) == 2

        queso = next(
            option for group in groups for option in group["options"]
            if option["name"] == "Queso extra"
        )
        grande = next(
            option for group in groups for option in group["options"]
            if option["name"] == "Grande"
        )

        order = await _create_order(
            client, customer_token, resto, item,
            option_ids=[queso["id"], grande["id"]],
        )
        assert order.status_code == 201
        data = order.json()
        assert float(data["items"][0]["unit_price"]) == 45.0
        assert float(data["subtotal"]) == 45.0
        assert len(data["items"][0]["options"]) == 2

        missing = await _create_order(
            client, customer_token, resto, item,
            option_ids=[queso["id"]],
        )
        assert missing.status_code == 400

    async def test_ingredient_group_uses_most_expensive_price(
        self, client, restaurant, owner_token, customer_token,
    ):
        resto, item = restaurant
        payload = {
            "groups": [{
                "name": "Ingredientes", "selection_type": "multiple",
                "pricing_mode": "max", "is_required": True,
                "min_selections": 1, "max_selections": 4, "sort_order": 1,
                "options": [
                    {"name": "Pepperoni", "price_delta": 80, "sort_order": 1},
                    {"name": "Puntas de bistec", "price_delta": 100, "sort_order": 2},
                    {"name": "Tocino", "price_delta": 90, "sort_order": 3},
                ],
            }]
        }
        created = await client.put(
            f"/api/v1/restaurants/{resto.id}/menu/{item.id}/options",
            json=payload,
            headers=_headers(owner_token),
        )
        assert created.status_code == 200
        options = created.json()[0]["options"]
        by_name = {option["name"]: option["id"] for option in options}

        order = await _create_order(
            client, customer_token, resto, item,
            option_ids=[by_name["Pepperoni"], by_name["Puntas de bistec"]],
        )
        assert order.status_code == 201
        data = order.json()
        assert float(data["items"][0]["unit_price"]) == 100.0
        portions = sorted(float(o["portion"]) for o in data["items"][0]["options"])
        assert portions == [0.5, 0.5]

        single = await _create_order(
            client, customer_token, resto, item,
            option_ids=[by_name["Pepperoni"]],
        )
        assert single.status_code == 201
        assert float(single.json()["items"][0]["unit_price"]) == 80.0

    async def test_option_from_other_item_is_rejected(
        self, client, restaurant, owner_token, customer_token, db_session,
    ):
        from app.models.menu_item import MenuItem

        resto, item = restaurant
        other = MenuItem(
            restaurant_id=resto.id, name="Otro platillo", price=20, is_available=True,
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        other_options = await client.put(
            f"/api/v1/restaurants/{resto.id}/menu/{other.id}/options",
            json={"groups": [{
                "name": "Extra", "selection_type": "single", "max_selections": 1,
                "options": [{"name": "A", "price_delta": 1}],
            }]},
            headers=_headers(owner_token),
        )
        foreign_option = other_options.json()[0]["options"][0]["id"]

        order = await _create_order(
            client, customer_token, resto, item,
            option_ids=[foreign_option],
        )
        assert order.status_code == 400


class TestServerCart:
    async def test_snapshot_roundtrip(self, client, customer_token):
        headers = _headers(customer_token)
        payload = {
            "items": [{
                "menu_item_id": "00000000-0000-0000-0000-000000000001",
                "name": "Pizza", "price": 120, "quantity": 2,
                "option_ids": [], "option_names": [],
            }],
            "restaurant_id": None,
        }
        saved = await client.put("/api/v1/profile/cart", json=payload, headers=headers)
        assert saved.status_code == 200
        loaded = await client.get("/api/v1/profile/cart", headers=headers)
        assert loaded.status_code == 200
        assert loaded.json()["items"][0]["name"] == "Pizza"
        assert loaded.json()["items"][0]["quantity"] == 2

        await client.put(
            "/api/v1/profile/cart",
            json={"items": [], "restaurant_id": None},
            headers=headers,
        )
        cleared = await client.get("/api/v1/profile/cart", headers=headers)
        assert cleared.json()["items"] == []


class TestLoyalty:
    async def test_visibility_setting_hides_points(self, client, superuser_token):
        headers = _headers(superuser_token)
        hidden = await client.patch(
            "/api/v1/settings",
            json={"values": {"LOYALTY_VISIBLE": "false"}},
            headers=headers,
        )
        assert hidden.status_code == 200
        config = await client.get("/api/v1/payments/config")
        assert config.status_code == 200
        assert config.json()["loyalty_visible"] is False
        await client.patch(
            "/api/v1/settings",
            json={"values": {"LOYALTY_VISIBLE": "true"}},
            headers=headers,
        )

    async def test_redeem_points_and_cancel_refunds(
        self, client, customer_token, restaurant, db_session,
    ):
        from app.core.security import decode_access_token

        resto, item = restaurant
        payload = decode_access_token(customer_token)
        user = await db_session.get(User, uuid.UUID(payload["sub"]))
        user.loyalty_points = 20
        await db_session.commit()

        estimate = await client.post(
            "/api/v1/orders/estimate-price",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1, "option_ids": []}],
                "delivery_address": "Calle 5 de Mayo 209",
                "delivery_location": {"lat": 20.6449, "lng": -100.9945},
                "payment_method": "cash",
                "points_to_redeem": 10,
            },
            headers=_headers(customer_token),
        )
        assert estimate.status_code == 200
        assert estimate.json()["points_redeemed"] == 10
        assert float(estimate.json()["loyalty_discount"]) == 10.0

        order = await _create_order(
            client, customer_token, resto, item, points_to_redeem=10,
        )
        assert order.status_code == 201
        data = order.json()
        assert data["points_redeemed"] == 10
        assert float(data["loyalty_discount"]) == 10.0

        me = await client.get("/api/v1/profile/me", headers=_headers(customer_token))
        assert me.json()["loyalty_points"] == 10

        cancelled = await client.post(
            f"/api/v1/orders/{data['id']}/cancel",
            json={"reason": "Prueba"},
            headers=_headers(customer_token),
        )
        assert cancelled.status_code == 200
        me = await client.get("/api/v1/profile/me", headers=_headers(customer_token))
        assert me.json()["loyalty_points"] == 20

    async def test_own_delivery_cash_points_are_platform_funded(
        self, client, customer_token, owner_token, restaurant, db_session,
    ):
        from app.core.security import decode_access_token

        resto, item = restaurant
        await client.patch(
            f"/api/v1/restaurants/{resto.id}/profile",
            json={"delivery_mode": "own"},
            headers=_headers(owner_token),
        )
        user = await db_session.get(User, uuid.UUID(decode_access_token(customer_token)["sub"]))
        user.loyalty_points = 30
        await db_session.commit()

        order = await _create_order(
            client, customer_token, resto, item, payment_method="cash", points_to_redeem=20,
        )
        assert order.status_code == 201
        data = order.json()
        commission = float(data["platform_commission"])
        flat = float(data["flat_usage_fee"])
        expected_owed = max(commission + flat - 20, 0)
        assert float(data["restaurant_owes_platform"]) == expected_owed

        delivered = await client.patch(
            f"/api/v1/restaurants/{resto.id}/orders/{data['id']}/status",
            json={"status": "delivered"},
            headers=_headers(owner_token),
        )
        assert delivered.status_code == 200

        earnings = await client.get(
            f"/api/v1/restaurants/{resto.id}/earnings",
            headers=_headers(owner_token),
        )
        assert earnings.status_code == 200
        body = earnings.json()
        expected_credit = max(20 - commission - flat, 0)
        assert float(body["loyalty_credit"]) == expected_credit
        assert float(body["restaurant_debt"]) == expected_owed
        assert float(body["available_for_payout"]) >= expected_credit

    async def test_delivery_awards_points_and_referral_bonus(
        self, client, restaurant, superuser_token,
    ):
        referrer = await client.post("/api/v1/auth/register", json={
            "name": "Referrer", "email": "referrer-loyalty@test.com", "password": "pass123",
        })
        referrer_token = referrer.json()["access_token"]
        profile = await client.get("/api/v1/profile/me", headers=_headers(referrer_token))
        code = profile.json()["referral_code"]
        assert code

        invited = await client.post("/api/v1/auth/register", json={
            "name": "Invited", "email": "invited-loyalty@test.com", "password": "pass123",
            "referral_code": code,
        })
        assert invited.status_code == 201
        invited_token = invited.json()["access_token"]

        await client.patch(
            "/api/v1/settings",
            json={"values": {"LOYALTY_ENABLED": "true", "LOYALTY_POINTS_PER_100": "100", "REFERRAL_BONUS_POINTS": "50"}},
            headers=_headers(superuser_token),
        )

        resto, item = restaurant
        order = await _create_order(client, invited_token, resto, item)
        assert order.status_code == 201
        order_id = order.json()["id"]

        delivered = await client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "delivered"},
            headers=_headers(superuser_token),
        )
        assert delivered.status_code == 200

        invited_me = await client.get("/api/v1/profile/me", headers=_headers(invited_token))
        assert invited_me.json()["loyalty_points"] == 80  # 30 earned + 50 bonus
        referrer_me = await client.get("/api/v1/profile/me", headers=_headers(referrer_token))
        assert referrer_me.json()["loyalty_points"] == 50

        # Awarding twice must not duplicate points.
        await client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "delivered"},
            headers=_headers(superuser_token),
        )
        invited_me = await client.get("/api/v1/profile/me", headers=_headers(invited_token))
        assert invited_me.json()["loyalty_points"] == 80


class TestPickupOrders:
    async def _enable(self, client, resto, owner_token):
        resp = await client.patch(
            f"/api/v1/restaurants/{resto.id}/profile",
            json={"pickup_enabled": True},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["pickup_enabled"] is True

    async def test_pickup_has_no_delivery_fee_or_address(
        self, client, restaurant, owner_token, customer_token,
    ):
        resto, item = restaurant
        await self._enable(client, resto, owner_token)

        estimate = await client.post(
            "/api/v1/orders/estimate-price",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "fulfillment_type": "pickup",
                "payment_method": "cash",
                "tip_amount": 20,
            },
            headers=_headers(customer_token),
        )
        assert estimate.status_code == 200
        assert float(estimate.json()["delivery_fee"]) == 0.0
        assert float(estimate.json()["tip_amount"]) == 0.0
        assert estimate.json()["fulfillment_type"] == "pickup"

        order = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "fulfillment_type": "pickup",
                "payment_method": "cash",
                "tip_amount": 20,
            },
            headers=_headers(customer_token),
        )
        assert order.status_code == 201
        data = order.json()
        assert data["fulfillment_type"] == "pickup"
        assert data["delivery_mode"] == "pickup"
        assert float(data["delivery_fee"]) == 0.0
        assert float(data["tip_amount"]) == 0.0
        assert float(data["delivery_earnings"]) == 0.0
        assert data["delivery_address"].startswith(resto.name)
        assert float(data["total"]) == float(data["subtotal"]) + float(data["flat_usage_fee"])

        delivered = await client.patch(
            f"/api/v1/restaurants/{resto.id}/orders/{data['id']}/status",
            json={"status": "delivered"},
            headers=_headers(owner_token),
        )
        assert delivered.status_code == 200

        earnings = await client.get(
            f"/api/v1/restaurants/{resto.id}/earnings",
            headers=_headers(owner_token),
        )
        assert earnings.status_code == 200
        expected_debt = float(data["platform_commission"]) + float(data["flat_usage_fee"])
        assert float(earnings.json()["restaurant_debt"]) == expected_debt

    async def test_pickup_must_be_enabled(
        self, client, restaurant, customer_token,
    ):
        resto, item = restaurant
        order = await client.post(
            "/api/v1/orders",
            json={
                "restaurant_id": str(resto.id),
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "fulfillment_type": "pickup",
                "payment_method": "cash",
            },
            headers=_headers(customer_token),
        )
        assert order.status_code == 400


class TestRestaurantRegistrationAndTeam:
    async def test_registration_approval_and_team_access(
        self, client, superuser_token,
    ):
        email = "nuevo-resto@test.com"
        registered = await client.post("/api/v1/restaurant-registration", json={
            "owner_name": "Dueño Nuevo",
            "email": email,
            "phone": "4121234567",
            "password": "pass123",
            "restaurant_name": "Cocina Nueva",
            "cuisine": "Mexicana",
            "address": "Calle 1, Centro",
            "lat": 20.6449,
            "lng": -100.9945,
        })
        assert registered.status_code == 201
        restaurant_id = registered.json()["restaurant_id"]

        blocked = await client.post("/api/v1/auth/login", json={
            "email": email, "password": "pass123",
        })
        assert blocked.status_code == 403

        listed = await client.get(
            "/api/v1/admin/restaurant-registrations",
            headers=_headers(superuser_token),
        )
        assert listed.status_code == 200
        assert any(r["id"] == restaurant_id and r["status"] == "pending" for r in listed.json())

        approved = await client.post(
            f"/api/v1/admin/restaurant-registrations/{restaurant_id}/approve",
            json={}, headers=_headers(superuser_token),
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "active"

        login = await client.post("/api/v1/auth/login", json={
            "email": email, "password": "pass123",
        })
        assert login.status_code == 200
        owner_token = login.json()["access_token"]

        detail = await client.get(
            f"/api/v1/restaurants/{restaurant_id}",
            headers=_headers(owner_token),
        )
        assert detail.status_code == 200
        assert detail.json()["viewer_role"] == "owner"

        member = await client.post(
            f"/api/v1/restaurants/{restaurant_id}/team",
            json={
                "name": "Cajero Uno", "email": "cajero-nuevo@test.com",
                "password": "pass123", "role": "cashier",
            },
            headers=_headers(owner_token),
        )
        assert member.status_code == 201

        staff_login = await client.post("/api/v1/auth/login", json={
            "email": "cajero-nuevo@test.com", "password": "pass123",
        })
        assert staff_login.status_code == 200
        staff_token = staff_login.json()["access_token"]

        staff_detail = await client.get(
            f"/api/v1/restaurants/{restaurant_id}",
            headers=_headers(staff_token),
        )
        assert staff_detail.status_code == 200
        assert staff_detail.json()["viewer_role"] == "cashier"

        orders = await client.get(
            f"/api/v1/restaurants/{restaurant_id}/orders",
            headers=_headers(staff_token),
        )
        assert orders.status_code == 200

        denied = await client.patch(
            f"/api/v1/restaurants/{restaurant_id}/profile",
            json={"name": "No permitido"},
            headers=_headers(staff_token),
        )
        assert denied.status_code == 403

    async def test_public_pages_and_password_reset_flow(self, client, superuser_token):
        manual = await client.get("/manuales/restaurante")
        assert manual.status_code == 200
        assert "Manual general del restaurante" in manual.text

        await client.patch(
            "/api/v1/settings",
            json={"values": {"APP_COMMISSION_PERCENTAGE": "12.5", "DELIVERY_BASE_FEE": "25"}},
            headers=_headers(superuser_token),
        )
        menu_manual = await client.get("/manuales/menu")
        assert menu_manual.status_code == 200
        assert "12.5 %" in menu_manual.text
        orders_manual = await client.get("/manuales/pedidos")
        assert orders_manual.status_code == 200
        assert "$25.00" in orders_manual.text

        page = await client.get("/web/register-restaurant")
        assert page.status_code == 200
        forgot = await client.get("/web/forgot-password")
        assert forgot.status_code == 200

        response = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "no-existe@test.com"},
        )
        assert response.status_code == 200
        assert "Si el correo está registrado" in response.json()["message"]

        invalid = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "invalido", "password": "nueva123"},
        )
        assert invalid.status_code == 400


class TestRechargesPage:
    async def test_recharges_coming_soon_page(self, client):
        resp = await client.get("/web/recargas")
        assert resp.status_code == 200
        assert "Tiempo aire y pago de servicios" in resp.text
        assert "Próximamente" in resp.text


class TestImageOptimization:
    async def test_logo_is_resized_and_converted_to_webp(
        self, client, restaurant, owner_token,
    ):
        import io
        from pathlib import Path

        from PIL import Image

        from app.services.file_service import UPLOAD_DIR

        resto, _ = restaurant
        buffer = io.BytesIO()
        Image.new("RGB", (2000, 1500), (180, 40, 40)).save(buffer, "PNG")

        resp = await client.post(
            f"/api/v1/restaurants/{resto.id}/logo",
            files={"file": ("logo.png", buffer.getvalue(), "image/png")},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200
        url = resp.json()["logo_url"]
        assert url.endswith(".webp")

        path = UPLOAD_DIR / Path(url).name
        try:
            with Image.open(path) as output:
                assert output.format == "WEBP"
                assert output.size == (800, 600)
        finally:
            path.unlink(missing_ok=True)

    async def test_rejects_non_image(
        self, client, restaurant, owner_token,
    ):
        resto, _ = restaurant
        resp = await client.post(
            f"/api/v1/restaurants/{resto.id}/logo",
            files={"file": ("notes.txt", b"hola", "text/plain")},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 400


class TestCancellationPolicy:
    async def test_policy_endpoint(self, client, customer_token):
        resp = await client.get(
            "/api/v1/orders/cancellation-policy",
            headers=_headers(customer_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "pending" in data["customer_allowed_statuses"]
        assert data["window_min"] >= 0

    async def test_customer_cancels_pending(
        self, client, restaurant, customer_token,
    ):
        resto, item = restaurant
        order = await _create_order(client, customer_token, resto, item)
        order_id = order.json()["id"]

        resp = await client.post(
            f"/api/v1/orders/{order_id}/cancel",
            json={"reason": "Ya no lo quiero"},
            headers=_headers(customer_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancellation_reason"] == "Ya no lo quiero"
        assert data["refund_status"] == "not_required"
        assert data["refund_amount"] == "0.00"

    async def test_customer_cannot_cancel_preparing(
        self, client, restaurant, customer_token, owner_token,
    ):
        resto, item = restaurant
        order = await _create_order(client, customer_token, resto, item)
        order_id = order.json()["id"]

        for status in ("confirmed", "preparing"):
            resp = await client.patch(
                f"/api/v1/restaurants/{resto.id}/orders/{order_id}/status",
                json={"status": status},
                headers=_headers(owner_token),
            )
            assert resp.status_code == 200

        resp = await client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers=_headers(customer_token),
        )
        assert resp.status_code == 400

    async def test_restaurant_cancels_preparing(
        self, client, restaurant, customer_token, owner_token,
    ):
        resto, item = restaurant
        order = await _create_order(client, customer_token, resto, item)
        order_id = order.json()["id"]

        for status in ("confirmed", "preparing"):
            await client.patch(
                f"/api/v1/restaurants/{resto.id}/orders/{order_id}/status",
                json={"status": status},
                headers=_headers(owner_token),
            )

        resp = await client.post(
            f"/api/v1/restaurants/{resto.id}/orders/{order_id}/cancel",
            json={"reason": "Sin ingredientes"},
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert resp.json()["cancellation_reason"] == "Sin ingredientes"


class TestSettingsApi:
    async def test_requires_superuser(self, client, customer_token):
        resp = await client.get("/api/v1/settings", headers=_headers(customer_token))
        assert resp.status_code == 403

    async def test_list_and_update(self, client, superuser_token):
        resp = await client.get("/api/v1/settings", headers=_headers(superuser_token))
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        names = [group["name"] for group in groups]
        assert "Comisiones" in names

        resp = await client.patch(
            "/api/v1/settings",
            json={"values": {"APP_COMMISSION_PERCENTAGE": "12.5", "MP_ENABLED": False}},
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 200
        assert resp.json()["updated"]["APP_COMMISSION_PERCENTAGE"] == "12.5"

        resp = await client.get("/api/v1/settings", headers=_headers(superuser_token))
        values = {
            item["key"]: item["value"]
            for group in resp.json()["groups"]
            for item in group["settings"]
        }
        assert values["APP_COMMISSION_PERCENTAGE"] == "12.5"

    async def test_rejects_out_of_range(self, client, superuser_token):
        resp = await client.patch(
            "/api/v1/settings",
            json={"values": {"APP_COMMISSION_PERCENTAGE": "101"}},
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 400

    async def test_rejects_unknown_key(self, client, superuser_token):
        resp = await client.patch(
            "/api/v1/settings",
            json={"values": {"NOT_A_REAL_KEY": "1"}},
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 400


class TestReports:
    async def test_superuser_summary(
        self, client, restaurant, customer_token, superuser_token,
    ):
        resto, item = restaurant
        order = await _create_order(client, customer_token, resto, item)
        assert order.status_code == 201

        resp = await client.get(
            "/api/v1/reports/summary",
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["orders_total"] == 1
        assert data["totals"]["gross_subtotal"] == "30.00"
        assert data["totals"]["commissions"] == "5.00"
        assert len(data["daily"]) >= 1

    async def test_owner_is_scoped(self, client, restaurant, customer_token, owner_token):
        resto, item = restaurant
        await _create_order(client, customer_token, resto, item)

        resp = await client.get(
            "/api/v1/reports/summary",
            headers=_headers(owner_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["orders_total"] == 1

    async def test_owner_cannot_read_other_restaurant(
        self, client, restaurant, customer_token,
    ):
        resto, item = restaurant
        await _create_order(client, customer_token, resto, item)

        # The customer owns no restaurant.
        resp = await client.get(
            "/api/v1/reports/summary",
            params={"restaurant_id": str(resto.id)},
            headers=_headers(customer_token),
        )
        assert resp.status_code == 403

    async def test_csv_export(
        self, client, restaurant, customer_token, superuser_token,
    ):
        resto, item = restaurant
        await _create_order(client, customer_token, resto, item)

        resp = await client.get(
            "/api/v1/reports/orders.csv",
            headers=_headers(superuser_token),
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "Folio" in resp.text
        assert "Horario Resto" in resp.text

    async def test_csv_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/orders.csv")
        assert resp.status_code in (401, 403)


class TestRestaurantTeamOrderStatus:
    async def test_all_order_roles_can_view_and_advance(
        self, client, restaurant, owner_token, customer_token,
    ):
        resto, item = restaurant
        tokens = {"owner": owner_token}
        for role in ("manager", "staff", "cashier", "kitchen"):
            email = f"rol-{role}-{uuid.uuid4().hex[:6]}@test.com"
            created = await client.post(
                f"/api/v1/restaurants/{resto.id}/team",
                json={
                    "name": f"Rol {role}",
                    "email": email,
                    "password": "pass123",
                    "role": role,
                },
                headers=_headers(owner_token),
            )
            assert created.status_code == 201, created.text
            login = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "pass123"},
            )
            assert login.status_code == 200, login.text
            tokens[role] = login.json()["access_token"]

        for role, token in tokens.items():
            order = await _create_order(client, customer_token, resto, item)
            assert order.status_code == 201, (role, order.text)
            order_id = order.json()["id"]

            detail = await client.get(
                f"/api/v1/orders/{order_id}", headers=_headers(token)
            )
            assert detail.status_code == 200, (role, detail.text)

            advanced = await client.patch(
                f"/api/v1/restaurants/{resto.id}/orders/{order_id}/status",
                json={"status": "confirmed"},
                headers=_headers(token),
            )
            assert advanced.status_code == 200, (role, advanced.text)
            assert advanced.json()["status"] == "confirmed"

