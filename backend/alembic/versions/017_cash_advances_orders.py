"""order cash advances for couriers

Revision ID: 017
Revises: 016
Create Date: 2026-11-09
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE cash_advances ADD COLUMN IF NOT EXISTS order_id UUID REFERENCES orders(id)")
    op.execute("ALTER TABLE cash_advances ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id)")
    op.execute("ALTER TABLE cash_advances ADD COLUMN IF NOT EXISTS settlement_method VARCHAR(20)")
    op.execute("""
        ALTER TABLE cash_advances
        ADD COLUMN IF NOT EXISTS pays_restaurant BOOLEAN NOT NULL DEFAULT TRUE
    """)
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS restaurant_paid_with_advance BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("UPDATE cash_advances SET status = 'approved' WHERE status = 'taken'")
    op.execute("""
        UPDATE cash_advances SET pays_restaurant = FALSE
        WHERE order_id IS NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cash_advances_order
        ON cash_advances (order_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cash_advances_delivery
        ON cash_advances (delivery_person_id, status)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_cash_advances_delivery")
    op.execute("DROP INDEX IF EXISTS idx_cash_advances_order")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS restaurant_paid_with_advance")
    op.execute("ALTER TABLE cash_advances DROP COLUMN IF EXISTS pays_restaurant")
    op.execute("ALTER TABLE cash_advances DROP COLUMN IF EXISTS settlement_method")
    op.execute("ALTER TABLE cash_advances DROP COLUMN IF EXISTS approved_by")
    op.execute("ALTER TABLE cash_advances DROP COLUMN IF EXISTS order_id")
