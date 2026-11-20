"""forma de pago de liquidaciones

Revision ID: 059
Revises: 058
Create Date: 2026-11-21
"""
from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurant_payouts ADD COLUMN IF NOT EXISTS "
        "settlement_method VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE delivery_payouts ADD COLUMN IF NOT EXISTS "
        "settlement_method VARCHAR(20)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE delivery_payouts DROP COLUMN IF EXISTS settlement_method")
    op.execute("ALTER TABLE restaurant_payouts DROP COLUMN IF EXISTS settlement_method")
