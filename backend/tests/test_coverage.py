"""Cobertura: solo se entrega dentro del municipio de Juventino Rosas."""

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import text

from app.models.setting import Setting
from app.services.coverage_service import ensure_coverage, is_inside_coverage

CENTRO = (20.6440, -100.9930)
LEON = (21.1213, -101.6822)

AREAS_SQL = """
    INSERT INTO postal_code_areas (cp, geom)
    VALUES ('38240', ST_Multi(ST_MakeEnvelope(-101.05, 20.58, -100.92, 20.72, 4326)))
"""


async def _areas(db) -> None:
    await db.execute(text("DELETE FROM postal_code_areas"))
    await db.execute(text(AREAS_SQL))
    await db.commit()


class TestCoverage:
    async def test_inside_polygon(self, db_session):
        await _areas(db_session)
        assert await is_inside_coverage(db_session, *CENTRO) is True

    async def test_outside_polygon(self, db_session):
        await _areas(db_session)
        assert await is_inside_coverage(db_session, *LEON) is False

    async def test_margin_covers_the_border(self, db_session):
        await _areas(db_session)
        # ~300 m al sur del polígono y ~780 m al sur.
        assert await is_inside_coverage(db_session, 20.5773, -100.99) is True
        assert await is_inside_coverage(db_session, 20.5730, -100.99) is False

    async def test_without_postal_data_does_not_block(self, db_session):
        await db_session.execute(text("DELETE FROM postal_code_areas"))
        await db_session.commit()
        assert await is_inside_coverage(db_session, *LEON) is None
        await ensure_coverage(db_session, *LEON)  # no debe lanzar

    async def test_rejects_outside_address(self, db_session):
        await _areas(db_session)
        with pytest.raises(HTTPException) as exc:
            await ensure_coverage(db_session, *LEON)
        assert exc.value.status_code == 400
        assert "Juventino Rosas" in exc.value.detail

    async def test_admin_can_disable(self, db_session):
        await _areas(db_session)
        db_session.add(Setting(key="COVERAGE_ENFORCE", value="false"))
        await db_session.commit()
        await ensure_coverage(db_session, *LEON)  # no debe lanzar


class TestCoverageEndpoint:
    async def test_inside(self, client: AsyncClient, db_session):
        await _areas(db_session)
        resp = await client.get(
            "/api/v1/geocode/coverage", params={"lat": CENTRO[0], "lng": CENTRO[1]}
        )
        assert resp.status_code == 200
        assert resp.json() == {"inside": True, "checked": True}

    async def test_outside(self, client: AsyncClient, db_session):
        await _areas(db_session)
        resp = await client.get(
            "/api/v1/geocode/coverage", params={"lat": LEON[0], "lng": LEON[1]}
        )
        assert resp.status_code == 200
        assert resp.json() == {"inside": False, "checked": True}
