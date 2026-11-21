"""citas de servicios a domicilio: direccion y ubicacion del cliente

Revision ID: 061
Revises: 060
Create Date: 2026-11-22
"""
from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS service_address TEXT"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS service_lat DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS service_lng DOUBLE PRECISION"
    )
    # Los servicios a domicilio usan la misma bandera de la tabla de servicios.
    op.execute(
        "ALTER TABLE business_services ADD COLUMN IF NOT EXISTS "
        "requires_address BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS service_lng")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS service_lat")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS service_address")
