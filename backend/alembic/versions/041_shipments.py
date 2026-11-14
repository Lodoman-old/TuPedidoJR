"""envios de negocio a cliente (motomandado)

Revision ID: 041
Revises: 040
Create Date: 2026-11-14
"""
from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shipments (
            id UUID PRIMARY KEY,
            store_id UUID NOT NULL REFERENCES restaurants(id),
            created_by_id UUID NOT NULL REFERENCES users(id),
            delivery_person_id UUID REFERENCES delivery_persons(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            recipient_name VARCHAR(150) NOT NULL,
            recipient_phone VARCHAR(20) NOT NULL,
            delivery_address TEXT NOT NULL,
            delivery_location GEOGRAPHY(POINT, 4326) NOT NULL,
            delivery_references TEXT,
            package_description TEXT NOT NULL,
            declared_value NUMERIC(10,2) NOT NULL DEFAULT 0,
            collect_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            amount_to_collect NUMERIC(10,2) NOT NULL DEFAULT 0,
            shipping_paid_by VARCHAR(10) NOT NULL DEFAULT 'store',
            delivery_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            platform_fee NUMERIC(10,2) NOT NULL DEFAULT 10,
            distance_km NUMERIC(8,2),
            tip_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            store_charge NUMERIC(10,2) NOT NULL DEFAULT 0,
            store_credit NUMERIC(10,2) NOT NULL DEFAULT 0,
            store_charge_settled BOOLEAN NOT NULL DEFAULT FALSE,
            store_credit_settled BOOLEAN NOT NULL DEFAULT FALSE,
            courier_earnings NUMERIC(10,2) NOT NULL DEFAULT 0,
            courier_settled BOOLEAN NOT NULL DEFAULT FALSE,
            cash_collected NUMERIC(10,2) NOT NULL DEFAULT 0,
            cash_remitted BOOLEAN NOT NULL DEFAULT FALSE,
            payment_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            cod_status VARCHAR(20) NOT NULL DEFAULT 'not_required',
            pickup_code VARCHAR(6),
            delivery_code VARCHAR(4),
            public_token VARCHAR(64) NOT NULL UNIQUE,
            pickup_photo_url TEXT,
            delivery_photo_url TEXT,
            accepted_at TIMESTAMPTZ,
            picked_up_at TIMESTAMPTZ,
            delivered_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ,
            cancelled_by UUID REFERENCES users(id),
            cancellation_reason TEXT,
            failure_reason TEXT,
            return_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_shipments_store_status "
        "ON shipments (store_id, status, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_shipments_courier_status "
        "ON shipments (delivery_person_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shipments")
