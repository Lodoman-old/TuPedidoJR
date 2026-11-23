"""Regresión: el resumen semanal debe usar las columnas reales de orders."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.services.business_summary_service import BUSINESS_STATS_SQL


async def test_business_stats_query_matches_schema(db_session):
    row = (
        await db_session.execute(
            text(BUSINESS_STATS_SQL),
            {"rid": uuid.uuid4(), "since": datetime.now(timezone.utc)},
        )
    ).mappings().one()
    assert row["orders"] == 0
    assert float(row["discounts"]) == 0
