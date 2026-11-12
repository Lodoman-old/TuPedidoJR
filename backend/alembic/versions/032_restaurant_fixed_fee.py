"""cuota fija por pedido para restaurantes

Revision ID: 032
Revises: 031
Create Date: 2026-11-11
"""
from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants "
        "ADD COLUMN IF NOT EXISTS commission_mode VARCHAR(20) NOT NULL DEFAULT 'percentage'"
    )
    op.execute(
        "ALTER TABLE restaurants "
        "ADD COLUMN IF NOT EXISTS fixed_fee NUMERIC(10, 2)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS fixed_fee")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS commission_mode")
