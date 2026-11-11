"""pickup orders at the restaurant

Revision ID: 027
Revises: 026
Create Date: 2026-11-10
"""
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE restaurants
        ADD COLUMN IF NOT EXISTS pickup_enabled BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS fulfillment_type VARCHAR(10) NOT NULL DEFAULT 'delivery'
    """)


def downgrade():
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS fulfillment_type")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS pickup_enabled")
