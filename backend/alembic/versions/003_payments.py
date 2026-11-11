"""add payment fields to orders

Revision ID: 003
Revises: 002
Create Date: 2026-06-02
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN payment_status VARCHAR(20) NOT NULL DEFAULT 'pending',
        ADD COLUMN payment_id VARCHAR(255),
        ADD COLUMN preference_id VARCHAR(255)
    """)


def downgrade():
    op.execute("""
        ALTER TABLE orders
        DROP COLUMN IF EXISTS payment_status,
        DROP COLUMN IF EXISTS payment_id,
        DROP COLUMN IF EXISTS preference_id
    """)
