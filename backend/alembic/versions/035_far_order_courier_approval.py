"""aprobacion de repartidor en pedidos lejanos y cuenta de reembolso

Revision ID: 035
Revises: 034
Create Date: 2026-11-12
"""
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS requires_courier_approval "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS awaiting_courier_at "
        "TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_account_holder VARCHAR(150)"
    )
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_bank VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_clabe VARCHAR(18)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS refund_clabe")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS refund_bank")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS refund_account_holder")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS awaiting_courier_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS requires_courier_approval")
