"""Recordatorios de onboarding a los 2 y 7 días."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.security import decode_access_token
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_schedule import RestaurantSchedule
from app.services import onboarding_reminder_service


async def _owner(client, email: str = "dueno-recordatorio@test.com") -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Dueño Recordatorio",
            "email": email,
            "phone": "4121234567",
            "password": "pass1234",
        },
    )
    assert resp.status_code == 201, resp.text
    return decode_access_token(resp.json()["access_token"])["sub"]


def _restaurant(owner_id: str, days_old: int, **overrides) -> Restaurant:
    reference = datetime.now(timezone.utc) - timedelta(days=days_old)
    data = dict(
        id=uuid.uuid4(),
        name="Negocio Recordatorio",
        slug=f"recordatorio-{uuid.uuid4().hex[:6]}",
        owner_id=uuid.UUID(str(owner_id)),
        location="SRID=4326;POINT(-100.99 20.64)",
        address="Calle 1",
        is_open=True,
        status="active",
        public_page_enabled=True,
        delivery_enabled=True,
        affiliation_expires_at=date.today() + timedelta(days=365),
        created_at=reference,
        approved_at=reference,
    )
    data.update(overrides)
    return Restaurant(**data)


@pytest.fixture
def sent_calls(monkeypatch):
    calls = []

    async def fake(
        db, to, name, restaurant_name, restaurant_id, missing, final=False
    ):
        calls.append(
            {"to": to, "name": name, "final": final, "missing": missing}
        )
        return True, "ok"

    monkeypatch.setattr(
        onboarding_reminder_service, "send_onboarding_reminder", fake
    )
    return calls


async def test_two_day_reminder_once(client, db_session, sent_calls):
    owner_id = await _owner(client)
    resto = _restaurant(owner_id, 3)
    db_session.add(resto)
    await db_session.commit()

    first = await onboarding_reminder_service.send_due_onboarding_reminders(db_session)
    assert first["two_day"] == 1
    assert len(sent_calls) == 1
    assert sent_calls[0]["final"] is False
    await db_session.refresh(resto)
    assert resto.onboarding_reminder_2_at is not None
    assert resto.onboarding_reminder_7_at is None

    second = await onboarding_reminder_service.send_due_onboarding_reminders(db_session)
    assert second["two_day"] == 0
    assert len(sent_calls) == 1


async def test_seven_day_reminder_marks_both(client, db_session, sent_calls):
    owner_id = await _owner(client, "dueno-recordatorio7@test.com")
    resto = _restaurant(owner_id, 8)
    db_session.add(resto)
    await db_session.commit()

    result = await onboarding_reminder_service.send_due_onboarding_reminders(db_session)
    assert result["seven_day"] == 1
    assert len(sent_calls) == 1
    assert sent_calls[0]["final"] is True
    await db_session.refresh(resto)
    assert resto.onboarding_reminder_2_at is not None
    assert resto.onboarding_reminder_7_at is not None


async def test_complete_business_is_not_reminded(client, db_session, sent_calls):
    owner_id = await _owner(client, "dueno-completo@test.com")
    resto = _restaurant(
        owner_id,
        8,
        description="Comida casera",
        phone="4121234567",
        logo_url="/static/uploads/logo.png",
    )
    db_session.add(resto)
    db_session.add(RestaurantSchedule(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        day_of_week=0,
        open_time=datetime.strptime("09:00", "%H:%M").time(),
        close_time=datetime.strptime("18:00", "%H:%M").time(),
        is_closed=False,
    ))
    db_session.add(MenuItem(
        id=uuid.uuid4(),
        restaurant_id=resto.id,
        name="Producto",
        price=Decimal("50.00"),
        preparation_time_min=5,
        is_available=True,
    ))
    await db_session.commit()

    result = await onboarding_reminder_service.send_due_onboarding_reminders(db_session)
    assert result["two_day"] == 0
    assert result["seven_day"] == 0
    assert sent_calls == []


async def test_onboarding_email_renders_without_smtp(client, db_session):
    from app.services.email_service import send_onboarding_reminder

    ok, detail = await send_onboarding_reminder(
        db_session,
        "dueno@example.com",
        "Dueño",
        "Negocio Demo",
        str(uuid.uuid4()),
        [{"label": "Horario", "description": "Configura tu horario"}],
        final=False,
    )
    assert ok is False
    assert "correo" in detail.lower() or "smtp" in detail.lower()

