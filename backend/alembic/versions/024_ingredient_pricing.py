"""ingredient groups priced by the most expensive selection

Revision ID: 024
Revises: 023
Create Date: 2026-11-10
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE menu_option_groups
        ADD COLUMN IF NOT EXISTS pricing_mode VARCHAR(20) NOT NULL DEFAULT 'delta'
    """)
    op.execute("""
        ALTER TABLE order_item_options
        ADD COLUMN IF NOT EXISTS portion DECIMAL(6,4) NOT NULL DEFAULT 1.0
    """)


def downgrade():
    op.execute("ALTER TABLE order_item_options DROP COLUMN IF EXISTS portion")
    op.execute("ALTER TABLE menu_option_groups DROP COLUMN IF EXISTS pricing_mode")
