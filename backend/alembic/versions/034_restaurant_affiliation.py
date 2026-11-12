"""afiliacion anual de restaurantes

Revision ID: 034
Revises: 033
Create Date: 2026-11-12
"""
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS affiliation_expires_at DATE"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS affiliation_reminder_on DATE"
    )
    # Los restaurantes existentes conservan un año de vigencia desde hoy.
    op.execute(
        "UPDATE restaurants SET affiliation_expires_at = CURRENT_DATE + 365 "
        "WHERE affiliation_expires_at IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS affiliation_reminder_on")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS affiliation_expires_at")
