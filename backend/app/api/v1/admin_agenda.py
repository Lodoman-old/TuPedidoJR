from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser
from app.db.session import get_db
from app.models.appointment_debt import AppointmentDebt
from app.models.business_ledger import BusinessLedger
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.appointment_settlement_service import business_balance, settle_restaurant

router = APIRouter()


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


@router.get("/agenda/balances")
async def agenda_balances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    rows = await db.execute(
        select(
            Restaurant.id,
            Restaurant.name,
            BusinessLedger.kind,
            func.coalesce(func.sum(BusinessLedger.amount), 0),
            func.count(BusinessLedger.id),
        )
        .join(BusinessLedger, BusinessLedger.restaurant_id == Restaurant.id)
        .where(BusinessLedger.status == "pending")
        .group_by(Restaurant.id, Restaurant.name, BusinessLedger.kind)
    )
    balances: dict[str, dict] = {}
    for restaurant_id, name, kind, total, count in rows.all():
        item = balances.setdefault(str(restaurant_id), {
            "restaurant_id": str(restaurant_id),
            "name": name,
            "credit": "0",
            "debit": "0",
            "credit_count": 0,
            "debit_count": 0,
        })
        item[kind] = str(total)
        item[f"{kind}_count"] = int(count)
    for item in balances.values():
        item["net"] = str(Decimal(item["credit"]) - Decimal(item["debit"]))
        detail = await business_balance(db, item["restaurant_id"])
        item["by_staff"] = [
            row for row in detail["by_staff"]
            if Decimal(row["credit"]) != 0 or Decimal(row["debit"]) != 0
        ]

    debts = await db.execute(
        select(
            AppointmentDebt.user_id,
            User.name,
            User.email,
            func.count(AppointmentDebt.id),
            func.coalesce(func.sum(AppointmentDebt.amount), 0),
        )
        .join(User, User.id == AppointmentDebt.user_id)
        .where(AppointmentDebt.status == "pending")
        .group_by(AppointmentDebt.user_id, User.name, User.email)
    )
    return {
        "businesses": sorted(balances.values(), key=lambda x: x["name"].lower()),
        "client_debts": [
            {
                "user_id": str(user_id),
                "name": name,
                "email": email,
                "count": int(count),
                "amount": str(amount),
            }
            for user_id, name, email, count, amount in debts.all()
        ],
    }


@router.post("/agenda/restaurants/{restaurant_id}/settle")
async def settle_business(
    restaurant_id: str,
    staff_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    restaurant = await db.get(Restaurant, _uuid(restaurant_id))
    if not restaurant:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    return await settle_restaurant(db, restaurant.id, staff_id=staff_id)


@router.get("/agenda/client-debts")
async def list_client_debts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(AppointmentDebt, User)
        .join(User, User.id == AppointmentDebt.user_id)
        .where(AppointmentDebt.status.in_(("pending", "assigned")))
        .order_by(AppointmentDebt.created_at.desc())
        .limit(200)
    )
    return [
        {
            "id": str(debt.id),
            "user_id": str(debt.user_id),
            "user_name": user.name,
            "user_email": user.email,
            "amount": str(debt.amount),
            "status": debt.status,
            "created_at": debt.created_at.isoformat() if debt.created_at else None,
        }
        for debt, user in result.all()
    ]


@router.post("/agenda/client-debts/{debt_id}/settle")
async def settle_client_debt(
    debt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    debt = await db.get(AppointmentDebt, _uuid(debt_id))
    if not debt:
        raise HTTPException(status_code=404, detail="Deuda no encontrada")
    debt.status = "paid"
    debt.settled_at = datetime.now(timezone.utc)
    if debt.restaurant_id and debt.business_amount and debt.business_amount > 0:
        db.add(BusinessLedger(
            restaurant_id=debt.restaurant_id,
            appointment_id=debt.appointment_id,
            kind="credit",
            amount=debt.business_amount,
            status="pending",
            notes="Parte del negocio por cita no asistida pagada en plataforma",
        ))
    await db.commit()
    return {"id": str(debt.id), "status": debt.status}
