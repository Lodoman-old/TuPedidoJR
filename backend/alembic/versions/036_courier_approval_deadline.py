"""cancelacion automatica de pedidos lejanos sin repartidor

Revision ID: 036
Revises: 035
Create Date: 2026-11-12
"""
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS courier_approval_deadline "
        "TIMESTAMP WITH TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS courier_approval_deadline")
