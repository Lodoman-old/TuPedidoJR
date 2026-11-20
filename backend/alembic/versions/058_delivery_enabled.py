"""reparto opcional por negocio

Revision ID: 058
Revises: 057
Create Date: 2026-11-21
"""
from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "delivery_enabled BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "UPDATE restaurants SET delivery_enabled = FALSE "
        "WHERE business_type IN ('services', 'rental', 'other')"
    )
    op.execute(
        "UPDATE restaurants SET pickup_enabled = TRUE "
        "WHERE delivery_enabled = FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS delivery_enabled")
