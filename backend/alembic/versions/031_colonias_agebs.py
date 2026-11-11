"""INE colonias and INEGI AGEB polygons for Juventino Rosas

Revision ID: 031
Revises: 030
Create Date: 2026-11-10
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None

DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data"


def _load(conn, table: str, columns: str, values_sql: str, features: list, mapper):
    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")
        if not geometry:
            continue
        params = mapper(props)
        if not params:
            continue
        params["geom"] = json.dumps(geometry)
        conn.execute(
            sa.text(f"""
                INSERT INTO {table} ({columns}, geom)
                VALUES ({values_sql}, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)))
                ON CONFLICT DO NOTHING
            """),
            params,
        )


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS colonia_areas (
            id SERIAL PRIMARY KEY,
            nombre VARCHAR(180) NOT NULL,
            cp VARCHAR(5),
            geom geometry(MultiPolygon, 4326) NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_colonia_areas_geom
        ON colonia_areas USING GIST (geom)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS ageb_areas (
            id SERIAL PRIMARY KEY,
            cvegeo VARCHAR(20) NOT NULL UNIQUE,
            cve_ageb VARCHAR(10) NOT NULL,
            ambito VARCHAR(10) NOT NULL,
            geom geometry(MultiPolygon, 4326) NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ageb_areas_geom
        ON ageb_areas USING GIST (geom)
    """)

    conn = op.get_bind()
    colonias_file = DATA_DIR / "colonias_juventino_rosas_ine.geojson"
    if colonias_file.exists():
        data = json.loads(colonias_file.read_text(encoding="utf-8"))

        def mapper(props):
            name = str(props.get("NOMBRE") or "").strip()
            if not name:
                return None
            cp = str(props.get("CP") or "").strip()
            if len(cp) != 5 or cp == "00000":
                cp = None
            return {"nombre": name, "cp": cp}

        _load(
            conn, "colonia_areas", "nombre, cp", ":nombre, :cp",
            data.get("features", []), mapper,
        )

    ageb_file = DATA_DIR / "agebs_juventino_rosas.geojson"
    if ageb_file.exists():
        data = json.loads(ageb_file.read_text(encoding="utf-8"))

        def mapper(props):
            cvegeo = str(props.get("cvegeo") or "").strip()
            cve_ageb = str(props.get("cve_ageb") or "").strip()
            if not cvegeo or not cve_ageb:
                return None
            return {
                "cvegeo": cvegeo,
                "cve_ageb": cve_ageb,
                "ambito": str(props.get("ambito") or "Urbano"),
            }

        _load(
            conn, "ageb_areas", "cvegeo, cve_ageb, ambito",
            ":cvegeo, :cve_ageb, :ambito",
            data.get("features", []), mapper,
        )


def downgrade():
    op.execute("DROP TABLE IF EXISTS ageb_areas CASCADE")
    op.execute("DROP TABLE IF EXISTS colonia_areas CASCADE")
