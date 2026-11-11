"""add coupons table and coupon fields to orders

Revision ID: 006
Revises: 005
Create Date: 2026-06-02
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS coupons (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            code VARCHAR(50) NOT NULL UNIQUE,
            description VARCHAR(255),
            discount_type VARCHAR(10) NOT NULL,
            discount_value DECIMAL(10,2) NOT NULL,
            min_order_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
            max_discount DECIMAL(10,2),
            max_uses INTEGER NOT NULL DEFAULT 0,
            current_uses INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            valid_from TIMESTAMPTZ,
            valid_until TIMESTAMPTZ,
            restaurant_id UUID REFERENCES restaurants(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_coupons_code ON coupons (code)")
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS coupon_id UUID REFERENCES coupons(id),
        ADD COLUMN IF NOT EXISTS coupon_code VARCHAR(50),
        ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(10,2) NOT NULL DEFAULT 0
    """)


def downgrade():
    op.execute("""
        ALTER TABLE orders
        DROP COLUMN IF EXISTS coupon_id,
        DROP COLUMN IF EXISTS coupon_code,
        DROP COLUMN IF EXISTS discount_amount
    """)
    op.execute("DROP TABLE IF EXISTS coupons CASCADE")
