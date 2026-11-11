"""postal code polygons for reverse geocoding

Revision ID: 030
Revises: 029
Create Date: 2026-11-10
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None

DATA_FILE = Path(__file__).resolve().parents[2] / "app" / "data" / "postal_codes_juventino_rosas.geojson"


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("""
        CREATE TABLE IF NOT EXISTS postal_code_areas (
            id SERIAL PRIMARY KEY,
            cp VARCHAR(5) NOT NULL UNIQUE,
            geom geometry(MultiPolygon, 4326) NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_postal_code_areas_geom
        ON postal_code_areas USING GIST (geom)
    """)
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        conn = op.get_bind()
        for feature in data.get("features", []):
            cp = str((feature.get("properties") or {}).get("cp") or "").strip()
            geometry = feature.get("geometry")
            if len(cp) != 5 or not geometry:
                continue
            conn.execute(
                sa.text("""
                    INSERT INTO postal_code_areas (cp, geom)
                    VALUES (:cp, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)))
                    ON CONFLICT (cp) DO UPDATE
                    SET geom = EXCLUDED.geom
                """),
                {"cp": cp, "geom": json.dumps(geometry)},
            )


def downgrade():
    op.execute("DROP TABLE IF EXISTS postal_code_areas CASCADE")
