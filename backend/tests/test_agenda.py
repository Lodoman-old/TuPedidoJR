"""Pruebas del módulo de agenda para barberías y salones."""

import uuid
from datetime import date, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import decode_access_token
from app.models.restaurant import Restaurant
from app.models.restaurant_schedule import RestaurantSchedule
from app.models.user import User
from app.services.appointment_payment_service import payment_plan


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
