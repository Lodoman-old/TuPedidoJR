"""menu item option groups and selected options on order items

Revision ID: 021
Revises: 020
Create Date: 2026-11-10
"""
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS menu_option_groups (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            menu_item_id UUID NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            selection_type VARCHAR(10) NOT NULL DEFAULT 'single',
            is_required BOOLEAN NOT NULL DEFAULT FALSE,
            min_selections INTEGER NOT NULL DEFAULT 0,
            max_selections INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS menu_options (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            group_id UUID NOT NULL REFERENCES menu_option_groups(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            price_delta DECIMAL(10,2) NOT NULL DEFAULT 0,
            is_available BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_item_options (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            order_item_id UUID NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
            option_id UUID REFERENCES menu_options(id),
            group_name VARCHAR(100) NOT NULL,
            name VARCHAR(100) NOT NULL,
            price_delta DECIMAL(10,2) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_menu_option_groups_item ON menu_option_groups (menu_item_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_menu_options_group ON menu_options (group_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_order_item_options_item ON order_item_options (order_item_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS order_item_options CASCADE")
    op.execute("DROP TABLE IF EXISTS menu_options CASCADE")
    op.execute("DROP TABLE IF EXISTS menu_option_groups CASCADE")
