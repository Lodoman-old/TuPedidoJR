"""adelanto al repartidor para mandados prepagados

Revision ID: 039
Revises: 038
Create Date: 2026-11-14
"""
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS advance_amount "
        "NUMERIC(10,2) NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS advance_status "
        "VARCHAR(20) NOT NULL DEFAULT 'not_required'"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS advance_difference "
        "NUMERIC(10,2)"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS advance_delivered_at "
        "TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS advance_settled_at "
        "TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS advance_settled_at")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS advance_delivered_at")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS advance_difference")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS advance_status")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS advance_amount")
