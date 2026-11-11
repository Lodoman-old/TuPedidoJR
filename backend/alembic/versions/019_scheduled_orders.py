"""scheduled orders

Revision ID: 019
Revises: 018
Create Date: 2026-11-10
"""
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ
    """)


def downgrade():
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS scheduled_for")
