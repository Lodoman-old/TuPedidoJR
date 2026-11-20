"""forma de pago de la afiliación

Revision ID: 057
Revises: 056
Create Date: 2026-11-20
"""
from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "affiliation_payment_method VARCHAR(20) NOT NULL DEFAULT 'transfer'"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "affiliation_plan_months INTEGER NOT NULL DEFAULT 12"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "affiliation_payment_requested_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS affiliation_payment_requested_at")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS affiliation_plan_months")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS affiliation_payment_method")
