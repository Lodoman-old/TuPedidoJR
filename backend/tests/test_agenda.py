"""Pruebas del módulo de agenda para barberías y salones."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.appointment import Appointment
from app.models.appointment_debt import AppointmentDebt
from app.models.menu_item import MenuItem
from app.models.receipt_validation import ReceiptValidation
from app.models.restaurant import Restaurant
from app.models.restaurant_schedule import RestaurantSchedule
from app.models.user import User
from app.services.appointment_payment_service import payment_plan
from app.services.appointment_reminder_service import _send_due


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Dueño Barbería", "email": "owner-agenda@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def customer_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Cliente Agenda", "email": "cliente-agenda@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def business(db_session, owner_token):
    owner_id = decode_access_token(owner_token)["sub"]
    target = date.today() + timedelta(days=3)
    resto = Restaurant(
        id=uuid.uuid4(),
        name="Barbería Agenda",
        owner_id=owner_id,
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 5 de Mayo 100",
        is_open=True,
        rating=4.8,
        delivery_radius_m=3000,
        delivery_fee=0,
        affiliation_expires_at=date.today() + timedelta(days=365),
        appointments_enabled=True,
    )
    db_session.add(resto)
    db_session.add(RestaurantSchedule(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        day_of_week=target.weekday(),
        open_time=datetime.strptime("09:00", "%H:%M").time(),
        close_time=datetime.strptime("13:00", "%H:%M").time(),
        is_closed=False,
    ))
    await db_session.commit()
    await db_session.refresh(resto)
    return resto, target


@pytest.fixture
async def service(client: AsyncClient, owner_token, business):
    resto, _ = business
    resp = await client.post(
        f"/api/v1/agenda/{resto.id}/services",
        headers=_headers(owner_token),
        json={"name": "Corte", "duration_min": 30, "price": 100},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def staff(client: AsyncClient, owner_token, business):
    resto, _ = business
    resp = await client.post(
        f"/api/v1/agenda/{resto.id}/staff",
        headers=_headers(owner_token),
        json={"name": "Ana", "role": "Estilista"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Admin Agenda", "email": "admin-agenda@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    user = await db_session.get(User, uuid.UUID(decode_access_token(token)["sub"]))
    user.is_superuser = True
    await db_session.commit()
    return token


@pytest.mark.asyncio
async def test_manage_services_and_staff(client, owner_token, business, service, staff):
    resto, _ = business
    services = await client.get(
        f"/api/v1/agenda/{resto.id}/services", headers=_headers(owner_token)
    )
    assert services.status_code == 200
    assert [s["name"] for s in services.json()] == ["Corte"]

    team = await client.get(
        f"/api/v1/agenda/{resto.id}/staff", headers=_headers(owner_token)
    )
    assert team.status_code == 200
    assert team.json()[0]["name"] == "Ana"


@pytest.mark.asyncio
async def test_customer_cannot_manage_services(client, customer_token, business):
    resto, _ = business
    resp = await client.get(
        f"/api/v1/agenda/{resto.id}/services", headers=_headers(customer_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_availability_lists_open_day(client, business, service, staff):
    resto, target = business
    resp = await client.get(
        f"/api/v1/agenda/{resto.id}/availability",
        params={"month": target.strftime("%Y-%m"), "service_id": service["id"]},
    )
    assert resp.status_code == 200
    days = {d["date"]: d["count"] for d in resp.json()["days"]}
    assert days.get(target.isoformat(), 0) > 0


@pytest.mark.asyncio
async def test_customer_books_cash_appointment(
    client, customer_token, business, service, staff
):
    resto, target = business
    payload = {
        "service_id": service["id"],
        "staff_id": staff["id"],
        "start_at": f"{target.isoformat()}T09:00:00",
        "client_name": "Cliente Agenda",
        "client_phone": "4121234567",
        "payment_mode": "cash",
    }
    resp = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "confirmed"
    assert float(data["price"]) == 100
    assert float(data["platform_fee"]) == 10
    assert float(data["business_fee"]) == 5

    again = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json=payload,
    )
    assert again.status_code == 409
    detail = again.json()["detail"]
    assert "libre" in detail or "ocupar" in detail


@pytest.mark.asyncio
async def test_booking_requires_active_affiliation(
    client, customer_token, business, service, staff, db_session
):
    resto, target = business
    resto.affiliation_expires_at = date.today() - timedelta(days=1)
    db_session.add(resto)
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start_at": f"{target.isoformat()}T10:00:00",
            "client_name": "Cliente Agenda",
        },
    )
    assert resp.status_code == 400
    assert "agenda" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_owner_marks_appointment_status(
    client, owner_token, customer_token, business, service, staff
):
    resto, target = business
    created = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start_at": f"{target.isoformat()}T11:00:00",
            "client_name": "Cliente Agenda",
        },
    )
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]

    day = await client.get(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(owner_token),
        params={"date": target.isoformat()},
    )
    assert day.status_code == 200
    assert len(day.json()) == 1

    updated = await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}",
        headers=_headers(owner_token),
        json={"status": "completed"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"


def test_payment_plan_cash():
    plan = payment_plan(100, "cash", 5, 5, 20)
    assert plan["online_amount"] == 0
    assert plan["cash_due"] == 105
    assert plan["business_credit"] == 0
    assert plan["business_debt"] == 10
    assert plan["payment_status"] == "cash_pending"


def test_payment_plan_deposit():
    plan = payment_plan(100, "deposit", 5, 5, 20)
    assert plan["deposit_amount"] == 20
    assert plan["online_amount"] == 25
    assert plan["cash_due"] == 80
    assert plan["business_credit"] == 15
    assert plan["business_debt"] == 0


def test_payment_plan_full():
    plan = payment_plan(100, "full", 5, 5, 20)
    assert plan["online_amount"] == 105
    assert plan["cash_due"] == 0
    assert plan["business_credit"] == 95
    assert plan["business_debt"] == 0


@pytest.mark.asyncio
async def test_transfer_booking_requires_proof(
    client, customer_token, business, service, staff
):
    resto, target = business
    resp = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start_at": f"{target.isoformat()}T12:00:00",
            "client_name": "Cliente Agenda",
            "payment_mode": "deposit",
        },
    )
    assert resp.status_code == 400
    assert "comprobante" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_full_transfer_booking_amounts(
    client, customer_token, business, service, staff, monkeypatch
):
    monkeypatch.setattr("app.api.v1.agenda.schedule_validation", lambda *a, **k: None)
    resto, target = business
    resp = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start_at": f"{target.isoformat()}T12:15:00",
            "client_name": "Cliente Agenda",
            "payment_mode": "full",
            "proof_url": "/static/uploads/transferencia.jpg",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["payment_mode"] == "full"
    assert float(data["online_amount"]) == 105
    assert float(data["business_credit"]) == 95
    assert float(data["cash_due"]) == 0
    assert data["receipt_status"] == "pending"


@pytest.mark.asyncio
async def test_proof_only_for_transfer_appointments(
    client, customer_token, business, service, staff, monkeypatch
):
    monkeypatch.setattr("app.api.v1.agenda.schedule_validation", lambda *a, **k: None)
    resto, target = business
    created = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start_at": f"{target.isoformat()}T12:30:00",
            "client_name": "Cliente Agenda",
            "payment_mode": "deposit",
            "proof_url": "/static/uploads/anticipo.jpg",
        },
    )
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]

    again = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}/proof",
        headers=_headers(customer_token),
        json={"proof_url": "/static/uploads/otro.jpg"},
    )
    assert again.status_code == 200
    assert again.json()["payment_status"] == "proof_review"

    cash = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start_at": f"{target.isoformat()}T09:30:00",
            "client_name": "Cliente Efectivo",
            "payment_mode": "cash",
        },
    )
    cash_id = cash.json()["id"]
    rejected = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments/{cash_id}/proof",
        headers=_headers(customer_token),
        json={"proof_url": "/static/uploads/no.jpg"},
    )
    assert rejected.status_code == 400


async def _book(client, resto, service, staff, token, start, mode="cash", proof=None):
    payload = {
        "service_id": service["id"],
        "staff_id": staff["id"],
        "start_at": f"{start.isoformat()}T09:00:00",
        "client_name": "Cliente Agenda",
        "payment_mode": mode,
    }
    if proof:
        payload["proof_url"] = proof
    return await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(token),
        json=payload,
    )


@pytest.mark.asyncio
async def test_pending_debt_is_added_to_next_cash_booking(
    client, customer_token, business, service, staff, db_session
):
    resto, target = business
    customer_id = decode_access_token(customer_token)["sub"]
    db_session.add(AppointmentDebt(
        user_id=customer_id,
        restaurant_id=resto.id,
        amount=10,
        platform_amount=5,
        business_amount=5,
        status="pending",
    ))
    await db_session.commit()

    created = await _book(client, resto, service, staff, customer_token, target)
    assert created.status_code == 201, created.text
    data = created.json()
    assert float(data["cash_due"]) == 115
    assert float(data["price"]) == 100

    debts = (await db_session.execute(
        AppointmentDebt.__table__.select().where(AppointmentDebt.status == "assigned")
    )).mappings().all()
    assert len(debts) == 1


@pytest.mark.asyncio
async def test_three_pending_debts_block_booking(
    client, customer_token, business, service, staff, db_session
):
    resto, target = business
    customer_id = decode_access_token(customer_token)["sub"]
    for _ in range(3):
        db_session.add(AppointmentDebt(
            user_id=customer_id,
            restaurant_id=resto.id,
            amount=10,
            platform_amount=5,
            business_amount=5,
            status="pending",
        ))
    await db_session.commit()

    blocked = await _book(client, resto, service, staff, customer_token, target)
    assert blocked.status_code == 403
    assert "3 citas" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_cash_no_show_creates_debt(
    client, owner_token, customer_token, business, service, staff, db_session
):
    resto, target = business
    created = await _book(client, resto, service, staff, customer_token, target)
    appointment_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}",
        headers=_headers(owner_token),
        json={"status": "no_show"},
    )
    assert updated.status_code == 200, updated.text

    debts = (await db_session.execute(
        AppointmentDebt.__table__.select().where(AppointmentDebt.status == "pending")
    )).mappings().all()
    assert len(debts) == 1
    assert float(debts[0]["amount"]) == 10


@pytest.mark.asyncio
async def test_completed_cash_records_business_debit(
    client, owner_token, customer_token, business, service, staff
):
    resto, target = business
    created = await _book(client, resto, service, staff, customer_token, target)
    appointment_id = created.json()["id"]

    await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}",
        headers=_headers(owner_token),
        json={"status": "completed"},
    )
    balance = await client.get(
        f"/api/v1/agenda/{resto.id}/balance", headers=_headers(owner_token)
    )
    assert balance.status_code == 200
    assert float(balance.json()["debit"]) == 10
    assert float(balance.json()["net"]) == -10


@pytest.mark.asyncio
async def test_completed_online_records_business_credit(
    client, owner_token, customer_token, business, service, staff, monkeypatch
):
    monkeypatch.setattr("app.api.v1.agenda.schedule_validation", lambda *a, **k: None)
    resto, target = business
    created = await _book(
        client, resto, service, staff, customer_token, target,
        mode="full", proof="/static/uploads/pago.jpg",
    )
    appointment_id = created.json()["id"]

    await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}",
        headers=_headers(owner_token),
        json={"status": "completed"},
    )
    balance = await client.get(
        f"/api/v1/agenda/{resto.id}/balance", headers=_headers(owner_token)
    )
    assert float(balance.json()["credit"]) == 95
    assert float(balance.json()["net"]) == 95


@pytest.mark.asyncio
async def test_online_no_show_refunds_and_compensates_business(
    client, owner_token, customer_token, business, service, staff, db_session, monkeypatch
):
    monkeypatch.setattr("app.api.v1.agenda.schedule_validation", lambda *a, **k: None)
    resto, target = business
    created = await _book(
        client, resto, service, staff, customer_token, target,
        mode="full", proof="/static/uploads/pago.jpg",
    )
    appointment_id = created.json()["id"]

    appointment = await db_session.get(Appointment, uuid.UUID(appointment_id))
    appointment.payment_status = "paid"
    db_session.add(appointment)
    await db_session.commit()

    updated = await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}",
        headers=_headers(owner_token),
        json={"status": "no_show"},
    )
    assert updated.status_code == 200
    assert float(updated.json()["refund_amount"]) == 95

    balance = await client.get(
        f"/api/v1/agenda/{resto.id}/balance", headers=_headers(owner_token)
    )
    assert float(balance.json()["credit"]) == 5


@pytest.mark.asyncio
async def test_affiliation_proof_upload_is_owner_only(
    client, owner_token, customer_token, business, monkeypatch
):
    monkeypatch.setattr(
        "app.api.v1.restaurants.schedule_affiliation_validation",
        lambda *a, **k: None,
    )
    resto, _ = business
    denied = await client.post(
        f"/api/v1/restaurants/{resto.id}/affiliation-proof",
        headers=_headers(customer_token),
        json={"proof_url": "/static/uploads/afiliacion.jpg"},
    )
    assert denied.status_code == 403

    ok = await client.post(
        f"/api/v1/restaurants/{resto.id}/affiliation-proof",
        headers=_headers(owner_token),
        json={"proof_url": "/static/uploads/afiliacion.jpg"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "review"


@pytest.mark.asyncio
async def test_admin_approves_affiliation_and_reject_restores(
    client, superuser_token, business, db_session
):
    resto, _ = business

    original = resto.affiliation_expires_at
    record = ReceiptValidation(
        entity_type="affiliation_payment",
        entity_id=resto.id,
        file_url="/static/uploads/afiliacion.jpg",
        expected_kind="transfer_receipt",
        expected_amount=500,
        status="review",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    approved = await client.post(
        f"/api/v1/admin/receipts/{record.id}/approve",
        headers=_headers(superuser_token),
    )
    assert approved.status_code == 200, approved.text

    await db_session.refresh(resto)
    assert resto.affiliation_expires_at > original

    rejected = await client.post(
        f"/api/v1/admin/receipts/{record.id}/reject",
        headers=_headers(superuser_token),
    )
    assert rejected.status_code == 200

    await db_session.refresh(resto)
    assert resto.affiliation_expires_at == original


@pytest.mark.asyncio
async def test_public_page_lists_services(
    client, business, service, staff, db_session
):
    resto, _ = business
    resto.slug = "barberia-agenda-publica"
    resto.public_page_enabled = True
    db_session.add(resto)
    await db_session.commit()

    resp = await client.get("/r/barberia-agenda-publica")
    assert resp.status_code == 200
    body = resp.text
    assert "Servicios" in body
    assert "Corte" in body
    assert "Agendar cita" in body


@pytest.mark.asyncio
async def test_listing_includes_services_filter(
    client, business, service, staff
):
    resto, _ = business
    resp = await client.get(
        "/api/v1/restaurants",
        params={"business_type": "all", "services": "true"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    match = next((r for r in rows if r["id"] == str(resto.id)), None)
    assert match is not None
    assert match["appointments_enabled"] is True


@pytest.mark.asyncio
async def test_any_professional_is_assigned_automatically(    client, owner_token, customer_token, business, service, staff
):
    resto, target = business
    created = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "start_at": f"{target.isoformat()}T09:00:00",
            "client_name": "Cliente Cualquiera",
            "payment_mode": "cash",
        },
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["staff_id"] is not None
    assert data["staff_name"] == "Ana"

    await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{data['id']}",
        headers=_headers(owner_token),
        json={"status": "completed"},
    )
    balance = await client.get(
        f"/api/v1/agenda/{resto.id}/balance", headers=_headers(owner_token)
    )
    ana = next(row for row in balance.json()["by_staff"] if row["name"] == "Ana")
    assert float(ana["client_fee"]) == 5
    assert ana["cash_count"] == 1


@pytest.mark.asyncio
async def test_balance_breaks_down_by_staff(
    client, owner_token, customer_token, superuser_token, business, service, staff
):
    resto, target = business
    created = await _book(client, resto, service, staff, customer_token, target)
    appointment_id = created.json()["id"]

    await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}",
        headers=_headers(owner_token),
        json={"status": "completed"},
    )
    balance = await client.get(
        f"/api/v1/agenda/{resto.id}/balance", headers=_headers(owner_token)
    )
    assert balance.status_code == 200
    by_staff = balance.json()["by_staff"]
    ana = next(row for row in by_staff if row["name"] == "Ana")
    assert float(ana["debit"]) == 10

    settled = await client.post(
        f"/api/v1/admin/agenda/restaurants/{resto.id}/settle",
        headers=_headers(superuser_token),
        params={"staff_id": staff["id"]},
    )
    assert settled.status_code == 200
    assert settled.json()["settled"] == 1

    after = await client.get(
        f"/api/v1/agenda/{resto.id}/balance", headers=_headers(owner_token)
    )
    ana_after = next(
        (row for row in after.json()["by_staff"] if row["name"] == "Ana"), None
    )
    assert ana_after is None or float(ana_after["debit"]) == 0


@pytest.mark.asyncio
async def test_products_can_be_reserved_with_appointment(
    client, customer_token, business, service, staff, db_session
):
    resto, target = business
    resto.pickup_enabled = True
    resto.is_open = True
    db_session.add(resto)
    today = date.today()
    open_today = await db_session.execute(
        RestaurantSchedule.__table__.select().where(
            RestaurantSchedule.restaurant_id == resto.id,
            RestaurantSchedule.day_of_week == today.weekday(),
        )
    )
    if not open_today.first():
        db_session.add(RestaurantSchedule(
            id=uuid.uuid4(),
            restaurant_id=resto.id,
            day_of_week=today.weekday(),
            open_time=datetime.strptime("00:00", "%H:%M").time(),
            close_time=datetime.strptime("23:59", "%H:%M").time(),
            is_closed=False,
        ))
    item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        name="Shampoo",
        description="Shampoo de prueba",
        price=100,
        is_available=True,
    )
    db_session.add(item)
    await db_session.commit()

    created = await _book(client, resto, service, staff, customer_token, target)
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]

    order = await client.post(
        "/api/v1/orders",
        headers=_headers(customer_token),
        json={
            "restaurant_id": str(resto.id),
            "items": [{"menu_item_id": str(item.id), "quantity": 1}],
            "payment_method": "cash",
            "fulfillment_type": "pickup",
            "appointment_id": appointment_id,
        },
    )
    assert order.status_code == 201, order.text
    assert order.json()["appointment_id"] == appointment_id


@pytest.mark.asyncio
async def test_reassign_and_cancel_notify_client(
    client, owner_token, customer_token, business, service, staff, monkeypatch
):
    resto, target = business
    second = await client.post(
        f"/api/v1/agenda/{resto.id}/staff",
        headers=_headers(owner_token),
        json={"name": "Diego", "role": "Barbero"},
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    created = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start_at": f"{target.isoformat()}T09:00:00",
            "client_name": "Cliente Demo",
            "payment_mode": "cash",
        },
    )
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]

    calls = []
    requests = []
    results = []
    monkeypatch.setattr(
        "app.api.v1.agenda.schedule_appointment_status",
        lambda appointment_id, event: calls.append((appointment_id, event)),
    )
    monkeypatch.setattr(
        "app.api.v1.agenda.schedule_reassign_request",
        lambda appointment_id: requests.append(appointment_id),
    )
    monkeypatch.setattr(
        "app.api.v1.agenda.schedule_reassign_result",
        lambda appointment_id, accepted: results.append((appointment_id, accepted)),
    )

    reassigned = await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}/staff",
        headers=_headers(owner_token),
        json={"staff_id": second_id},
    )
    assert reassigned.status_code == 200, reassigned.text
    assert reassigned.json()["staff_name"] == "Diego"
    assert reassigned.json()["reassign_status"] == "pending"
    assert requests[-1] == appointment_id

    accepted = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}/reassign/accept",
        headers=_headers(customer_token),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["reassign_status"] == "accepted"
    assert results[-1] == (appointment_id, True)

    # Diego ya tiene otra cita a las 10:00: no se le puede reasignar otra a la misma hora.
    ana_ten = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start_at": f"{target.isoformat()}T10:00:00",
            "client_name": "Cliente Ana",
        },
    )
    diego_booked = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments",
        headers=_headers(customer_token),
        json={
            "service_id": service["id"],
            "staff_id": second_id,
            "start_at": f"{target.isoformat()}T10:00:00",
            "client_name": "Cliente Diego",
        },
    )
    assert diego_booked.status_code == 201
    assert ana_ten.status_code == 201

    blocked = await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{ana_ten.json()['id']}/staff",
        headers=_headers(owner_token),
        json={"staff_id": second_id},
    )
    assert blocked.status_code == 409
    assert "otra cita" in blocked.json()["detail"]

    cancelled = await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}",
        headers=_headers(owner_token),
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert calls[-1] == (appointment_id, "cancelled")


@pytest.mark.asyncio
async def test_client_rejects_reassign_and_cancels(
    client, owner_token, customer_token, business, service, staff, monkeypatch
):
    resto, target = business
    second = await client.post(
        f"/api/v1/agenda/{resto.id}/staff",
        headers=_headers(owner_token),
        json={"name": "Diego", "role": "Barbero"},
    )
    second_id = second.json()["id"]
    created = await _book(client, resto, service, staff, customer_token, target)
    appointment_id = created.json()["id"]

    results = []
    monkeypatch.setattr(
        "app.api.v1.agenda.schedule_reassign_request", lambda *a: None
    )
    monkeypatch.setattr(
        "app.api.v1.agenda.schedule_reassign_result",
        lambda appointment_id, accepted: results.append((appointment_id, accepted)),
    )
    await client.patch(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}/staff",
        headers=_headers(owner_token),
        json={"staff_id": second_id},
    )

    rejected = await client.post(
        f"/api/v1/agenda/{resto.id}/appointments/{appointment_id}/reassign/reject",
        headers=_headers(customer_token),
    )
    assert rejected.status_code == 200, rejected.text
    data = rejected.json()
    assert data["status"] == "cancelled"
    assert data["reassign_status"] == "rejected"
    assert results[-1] == (appointment_id, False)

    mine = await client.get(
        "/api/v1/agenda/my-appointments", headers=_headers(customer_token)
    )
    assert mine.status_code == 200
    row = next(item for item in mine.json() if item["id"] == appointment_id)
    assert row["status"] == "cancelled"
    assert row["restaurant_name"] == "Barbería Agenda"


@pytest.mark.asyncio
async def test_appointment_reminders_are_queued(
    client, customer_token, business, service, staff, db_session, monkeypatch
):
    resto, _ = business
    customer_id = uuid.UUID(decode_access_token(customer_token)["sub"])
    now = datetime.now(timezone.utc)

    client_appt = Appointment(
        restaurant_id=resto.id,
        service_id=uuid.UUID(service["id"]),
        staff_id=uuid.UUID(staff["id"]),
        client_user_id=customer_id,
        client_name="Cliente Demo",
        start_at=now + timedelta(minutes=30),
        end_at=now + timedelta(minutes=60),
        status="confirmed",
        price=100,
        payment_mode="cash",
        payment_status="cash_pending",
        platform_fee=10,
        business_fee=5,
    )
    business_appt = Appointment(
        restaurant_id=resto.id,
        service_id=uuid.UUID(service["id"]),
        staff_id=uuid.UUID(staff["id"]),
        client_user_id=customer_id,
        client_name="Cliente Demo",
        start_at=now + timedelta(minutes=2),
        end_at=now + timedelta(minutes=32),
        status="confirmed",
        price=100,
        payment_mode="cash",
        payment_status="cash_pending",
        platform_fee=10,
        business_fee=5,
    )
    db_session.add_all([client_appt, business_appt])
    await db_session.commit()

    calls = []
    monkeypatch.setattr(
        "app.services.appointment_reminder_service.schedule_appointment_client_reminder",
        lambda appointment_id: calls.append(("client", appointment_id)),
    )
    monkeypatch.setattr(
        "app.services.appointment_reminder_service.schedule_appointment_business_now",
        lambda appointment_id: calls.append(("business", appointment_id)),
    )

    await _send_due(db_session)
    await db_session.refresh(client_appt)
    await db_session.refresh(business_appt)

    assert client_appt.client_reminder_sent_at is not None
    assert business_appt.business_reminder_sent_at is not None
    assert ("client", str(client_appt.id)) in calls
    assert ("business", str(business_appt.id)) in calls
