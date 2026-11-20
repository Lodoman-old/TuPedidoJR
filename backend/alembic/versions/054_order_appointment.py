"""productos apartados con una cita

Revision ID: 054
Revises: 053
Create Date: 2026-11-20
"""
from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS appointment_id UUID "
        "REFERENCES appointments(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_appointment_id ON orders (appointment_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_appointment_id")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS appointment_id")
