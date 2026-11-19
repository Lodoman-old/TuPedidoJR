"""agenda de citas para barberías y salones

Revision ID: 049
Revises: 048
Create Date: 2026-11-19
"""
from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "appointments_enabled BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_services (
            id UUID PRIMARY KEY,
            restaurant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            name VARCHAR(120) NOT NULL,
            description TEXT,
            duration_min INTEGER NOT NULL DEFAULT 30,
            price NUMERIC(10,2) NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_business_services_restaurant "
        "ON business_services (restaurant_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_staff (
            id UUID PRIMARY KEY,
            restaurant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            role VARCHAR(60),
            is_active BOOLEAN NOT NULL DEFAULT true,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_business_staff_restaurant "
        "ON business_staff (restaurant_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id UUID PRIMARY KEY,
            restaurant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            service_id UUID REFERENCES business_services(id) ON DELETE SET NULL,
            staff_id UUID REFERENCES business_staff(id) ON DELETE SET NULL,
            client_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            client_name VARCHAR(120) NOT NULL,
            client_phone VARCHAR(25),
            start_at TIMESTAMPTZ NOT NULL,
            end_at TIMESTAMPTZ NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'confirmed',
            price NUMERIC(10,2) NOT NULL DEFAULT 0,
            payment_mode VARCHAR(20) NOT NULL DEFAULT 'cash',
            payment_status VARCHAR(20) NOT NULL DEFAULT 'cash_pending',
            deposit_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            platform_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            business_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            proof_url TEXT,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_appointments_restaurant_start "
        "ON appointments (restaurant_id, start_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_appointments_staff_start "
        "ON appointments (staff_id, start_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_staff_start_active "
        "ON appointments (staff_id, start_at) "
        "WHERE status IN ('pending', 'confirmed') AND staff_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS appointments")
    op.execute("DROP TABLE IF EXISTS business_staff")
    op.execute("DROP TABLE IF EXISTS business_services")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS appointments_enabled")
