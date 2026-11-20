"""recargas manuales

Revision ID: 060
Revises: 059
Create Date: 2026-11-21
"""
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS recarga_orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            customer_name VARCHAR(150),
            delivery_person_id UUID REFERENCES delivery_persons(id) ON DELETE SET NULL,
            order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
            company VARCHAR(40) NOT NULL,
            phone VARCHAR(20) NOT NULL,
            amount NUMERIC(10, 2) NOT NULL,
            fee NUMERIC(10, 2) NOT NULL DEFAULT 0,
            total NUMERIC(10, 2) NOT NULL,
            payment_method VARCHAR(10) NOT NULL DEFAULT 'cash',
            payment_status VARCHAR(15) NOT NULL DEFAULT 'pending',
            status VARCHAR(15) NOT NULL DEFAULT 'pending',
            provider_reference VARCHAR(100),
            error_message TEXT,
            notes TEXT,
            debt_applied BOOLEAN NOT NULL DEFAULT FALSE,
            credit_applied BOOLEAN NOT NULL DEFAULT FALSE,
            paid_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            refunded_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recarga_orders_created_at "
        "ON recarga_orders (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recarga_orders_delivery_person "
        "ON recarga_orders (delivery_person_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recarga_orders")
