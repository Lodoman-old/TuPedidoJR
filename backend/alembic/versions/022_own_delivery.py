"""restaurant own-delivery mode and cash settlement debt

Revision ID: 022
Revises: 021
Create Date: 2026-11-10
"""
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE restaurants
        ADD COLUMN IF NOT EXISTS delivery_mode VARCHAR(20) NOT NULL DEFAULT 'platform'
    """)
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS delivery_mode VARCHAR(20) NOT NULL DEFAULT 'platform'
    """)
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS restaurant_owes_platform DECIMAL(10,2) NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS restaurant_charge_settled BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade():
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS restaurant_charge_settled")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS restaurant_owes_platform")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS delivery_mode")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS delivery_mode")
