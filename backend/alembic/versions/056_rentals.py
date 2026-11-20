"""tipo de negocio de rentas: articulos, existencias y reservas

Revision ID: 056
Revises: 055
Create Date: 2026-11-20
"""
from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE business_services ADD COLUMN IF NOT EXISTS "
        "stock INTEGER NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE business_services ADD COLUMN IF NOT EXISTS "
        "requires_address BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE business_services ADD COLUMN IF NOT EXISTS "
        "is_rental BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rental_bookings (
            id UUID PRIMARY KEY,
            restaurant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            client_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            client_name VARCHAR(120) NOT NULL,
            client_phone VARCHAR(25),
            start_at TIMESTAMPTZ NOT NULL,
            end_at TIMESTAMPTZ NOT NULL,
            address TEXT,
            location GEOGRAPHY(POINT, 4326),
            status VARCHAR(20) NOT NULL DEFAULT 'confirmed',
            payment_mode VARCHAR(20) NOT NULL DEFAULT 'cash',
            payment_status VARCHAR(20) NOT NULL DEFAULT 'cash_pending',
            deposit_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            deposit_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
            online_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            cash_due NUMERIC(10,2) NOT NULL DEFAULT 0,
            business_credit NUMERIC(10,2) NOT NULL DEFAULT 0,
            business_debt NUMERIC(10,2) NOT NULL DEFAULT 0,
            platform_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            business_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            proof_url TEXT,
            receipt_status VARCHAR(20) NOT NULL DEFAULT 'none',
            paid_at TIMESTAMPTZ,
            refund_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            client_reminder_sent_at TIMESTAMPTZ,
            business_reminder_sent_at TIMESTAMPTZ,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rental_bookings_restaurant_start "
        "ON rental_bookings (restaurant_id, start_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rental_bookings_client "
        "ON rental_bookings (client_user_id, start_at)"
    )
    op.execute(
        "ALTER TABLE business_ledger ADD COLUMN IF NOT EXISTS "
        "rental_booking_id UUID REFERENCES rental_bookings(id) ON DELETE SET NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rental_booking_items (
            id UUID PRIMARY KEY,
            booking_id UUID NOT NULL REFERENCES rental_bookings(id) ON DELETE CASCADE,
            service_id UUID REFERENCES business_services(id) ON DELETE SET NULL,
            name VARCHAR(120) NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,
            duration_min INTEGER NOT NULL DEFAULT 60,
            start_at TIMESTAMPTZ NOT NULL,
            end_at TIMESTAMPTZ NOT NULL,
            subtotal NUMERIC(10,2) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rental_booking_items_booking "
        "ON rental_booking_items (booking_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rental_booking_items_service_start "
        "ON rental_booking_items (service_id, start_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rental_booking_items")
    op.execute("DROP TABLE IF EXISTS rental_bookings")
    op.execute("ALTER TABLE business_services DROP COLUMN IF EXISTS is_rental")
    op.execute("ALTER TABLE business_services DROP COLUMN IF EXISTS requires_address")
    op.execute("ALTER TABLE business_services DROP COLUMN IF EXISTS stock")
