"""recordatorios de citas

Revision ID: 052
Revises: 051
Create Date: 2026-11-19
"""
from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "client_reminder_sent_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "business_reminder_sent_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS business_reminder_sent_at")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS client_reminder_sent_at")
