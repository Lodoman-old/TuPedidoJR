"""Métricas de audiencia para el panel de seguridad y publicidad."""
from datetime import date, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery_person import DeliveryPerson
from app.models.push_token import PushToken
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.schedule_service import local_today


async def audience_overview(db: AsyncSession) -> dict:
    today = await local_today(db)
    start = today - timedelta(days=6)

    push_devices = (
        await db.execute(
            select(func.count(PushToken.id)).where(PushToken.is_active.is_(True))
        )
    ).scalar_one() or 0
    push_users = (
        await db.execute(
            select(func.count(func.distinct(PushToken.user_id))).where(
                PushToken.is_active.is_(True)
            )
        )
    ).scalar_one() or 0
    platform_rows = (
        await db.execute(
            select(PushToken.platform, func.count(PushToken.id))
            .where(PushToken.is_active.is_(True))
            .group_by(PushToken.platform)
        )
    ).all()

    today_row = (
        await db.execute(
            text(
                """
                SELECT count(*) AS users, coalesce(sum(views), 0) AS views
                FROM daily_visits
                WHERE visited_on = :day AND role = 'customer'
                """
            ),
            {"day": today},
        )
    ).mappings().one()

    week_rows = (
        await db.execute(
            text(
                """
                SELECT visited_on, count(*) AS users, coalesce(sum(views), 0) AS views
                FROM daily_visits
                WHERE visited_on >= :start AND role = 'customer'
                GROUP BY visited_on
                ORDER BY visited_on
                """
            ),
            {"start": start},
        )
    ).mappings().all()
    by_day = {row["visited_on"]: row for row in week_rows}
    week = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        row = by_day.get(day)
        week.append(
            {
                "date": day.isoformat(),
                "users": int(row["users"]) if row else 0,
                "views": int(row["views"]) if row else 0,
            }
        )

    normal_users = (
        await db.execute(
            select(func.count(User.id)).where(
                User.is_superuser.is_(False),
                User.is_active.is_(True),
            )
        )
    ).scalar_one() or 0
    active_businesses = (
        await db.execute(
            select(func.count(Restaurant.id)).where(
                Restaurant.status == "active",
                Restaurant.affiliation_expires_at.is_not(None),
                Restaurant.affiliation_expires_at >= today,
            )
        )
    ).scalar_one() or 0
    available_couriers = (
        await db.execute(
            select(func.count(DeliveryPerson.id)).where(
                DeliveryPerson.is_available.is_(True)
            )
        )
    ).scalar_one() or 0

    return {
        "push_devices": int(push_devices),
        "push_users": int(push_users),
        "push_by_platform": {
            (platform or "otro"): int(count) for platform, count in platform_rows
        },
        "visits_today": int(today_row["users"] or 0),
        "views_today": int(today_row["views"] or 0),
        "visits_7d": week,
        "normal_users": int(normal_users),
        "active_businesses": int(active_businesses),
        "available_couriers": int(available_couriers),
        "today": today.isoformat(),
    }
