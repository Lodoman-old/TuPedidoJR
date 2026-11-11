"""Tests for the Juventino Rosas postal-code catalog."""

from httpx import AsyncClient


class TestPostalCode:
    async def test_known_cp(self, client: AsyncClient):
        resp = await client.get("/api/v1/geocode/postal-code/38240")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cp"] == "38240"
        assert data["municipio"] == "Santa Cruz de Juventino Rosas"
        assert any(c["nombre"] == "Santa Cruz de Juventino Rosas Centro" for c in data["colonias"])

    async def test_unknown_cp(self, client: AsyncClient):
        resp = await client.get("/api/v1/geocode/postal-code/99999")
        assert resp.status_code == 404

    async def test_reverse_postal_code_with_postgis(self, client: AsyncClient, db_session):
        from sqlalchemy import text

        await db_session.execute(text("""
            INSERT INTO postal_code_areas (cp, geom)
            VALUES ('38240', ST_Multi(ST_MakeEnvelope(-101.00, 20.64, -100.99, 20.65, 4326)))
        """))
        await db_session.execute(text("""
            INSERT INTO colonia_areas (nombre, cp, geom)
            VALUES ('ZONA CENTRO', '38240', ST_Multi(ST_MakeEnvelope(-101.00, 20.64, -100.99, 20.65, 4326)))
        """))
        await db_session.execute(text("""
            INSERT INTO ageb_areas (cvegeo, cve_ageb, ambito, geom)
            VALUES ('1103500010001', '0001', 'Urbano', ST_Multi(ST_MakeEnvelope(-101.00, 20.64, -100.99, 20.65, 4326)))
        """))
        await db_session.commit()
        resp = await client.get(
            "/api/v1/geocode/postal-code-reverse",
            params={"lat": 20.6440, "lng": -100.9968},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cp"] == "38240"
        assert data["colonia"] == "ZONA CENTRO"
        assert data["ageb"] == "0001"
        assert data["source"] == "postgis"
