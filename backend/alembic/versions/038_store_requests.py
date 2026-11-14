"""tiendas, catalogo y solicitudes de producto

Revision ID: 038
Revises: 037
Create Date: 2026-11-14
"""
from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS business_type "
        "VARCHAR(30) NOT NULL DEFAULT 'restaurant'"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS catalog_enabled "
        "BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS accepts_custom_requests "
        "BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_restaurants_business_type "
        "ON restaurants (business_type)"
    )
    op.execute("ALTER TABLE order_items ALTER COLUMN menu_item_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS trusted_customer "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS prepayment_required "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS prepayment_proof_url TEXT"
    )
    op.execute(
        "ALTER TABLE mandados ADD COLUMN IF NOT EXISTS prepayment_confirmed_at "
        "TIMESTAMPTZ"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS store_requests (
            id UUID PRIMARY KEY,
            store_id UUID NOT NULL REFERENCES restaurants(id),
            user_id UUID NOT NULL REFERENCES users(id),
            description TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            reference_photo_url TEXT,
            budget NUMERIC(10,2),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            quoted_price NUMERIC(10,2),
            store_notes TEXT,
            delivery_address TEXT NOT NULL,
            delivery_location GEOGRAPHY(POINT, 4326) NOT NULL,
            payment_method VARCHAR(10) NOT NULL DEFAULT 'cash',
            notes TEXT,
            order_id UUID REFERENCES orders(id),
            responded_at TIMESTAMPTZ,
            confirmed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_requests_store_status "
        "ON store_requests (store_id, status, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_requests_user_created "
        "ON store_requests (user_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS store_requests")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS prepayment_confirmed_at")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS prepayment_proof_url")
    op.execute("ALTER TABLE mandados DROP COLUMN IF EXISTS prepayment_required")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS trusted_customer")
    op.execute("ALTER TABLE order_items ALTER COLUMN menu_item_id SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_restaurants_business_type")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS accepts_custom_requests")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS catalog_enabled")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS business_type")
