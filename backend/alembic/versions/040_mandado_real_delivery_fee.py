"""envio real por kilometros en mandados abiertos

Revision ID: 040
Revises: 039
Create Date: 2026-11-14
"""
from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE mandados ADD COLUMN IF NOT EXISTS pickup_address TEXT")
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS pickup_location "
        "GEOGRAPHY(POINT, 4326)"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS delivery_fee_estimated "
        "NUMERIC(10,2)"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS delivery_fee_final "
        "NUMERIC(10,2)"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS distance_km_estimated "
        "NUMERIC(8,2)"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS distance_km_final "
        "NUMERIC(8,2)"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS fee_adjustment_amount "
        "NUMERIC(10,2) NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS fee_adjustment_status "
        "VARCHAR(20) NOT NULL DEFAULT 'not_required'"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS pickup_confirmed_at "
        "TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS fee_customer_responded_at "
        "TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS fee_customer_responded_at")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS pickup_confirmed_at")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS fee_adjustment_status")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS fee_adjustment_amount")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS distance_km_final")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS distance_km_estimated")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS delivery_fee_final")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS delivery_fee_estimated")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS pickup_location")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS pickup_address")
