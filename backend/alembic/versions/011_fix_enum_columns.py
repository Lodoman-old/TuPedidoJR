"""fix status order_status to varchar

Revision ID: 011
Revises: 010
Create Date: 2026-06-05
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP INDEX IF EXISTS idx_orders_status")
    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(20)")
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'pending'")
    op.execute("DROP TYPE IF EXISTS order_status CASCADE")
    op.execute("DROP TYPE IF EXISTS order_estatus CASCADE")


def downgrade():
    op.execute("CREATE TYPE order_status AS ENUM ('pending', 'confirmed', 'preparing', 'ready', 'in_delivery', 'delivered', 'cancelled')")
    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE order_status USING status::text::order_status")
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'pending'::order_status")
    op.execute("CREATE INDEX idx_orders_status ON orders (status) WHERE status IN ('pending', 'confirmed', 'preparing', 'in_delivery')")
