"""planes de afiliacion prepagados

Revision ID: 055
Revises: 054
Create Date: 2026-11-20
"""
from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE receipt_validations ADD COLUMN IF NOT EXISTS "
        "plan_months INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE receipt_validations DROP COLUMN IF EXISTS plan_months")
