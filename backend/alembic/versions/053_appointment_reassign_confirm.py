"""confirmacion del cliente al reasignar una cita

Revision ID: 053
Revises: 052
Create Date: 2026-11-19
"""
from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "reassign_status VARCHAR(20) NOT NULL DEFAULT 'none'"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "reassign_requested_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS reassign_requested_at")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS reassign_status")
