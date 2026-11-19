"""no-show, deudas del cliente y saldos del negocio

Revision ID: 051
Revises: 050
Create Date: 2026-11-19
"""
from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "refund_amount NUMERIC(10,2) NOT NULL DEFAULT 0"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS appointment_debts (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            restaurant_id UUID REFERENCES restaurants(id) ON DELETE SET NULL,
            appointment_id UUID REFERENCES appointments(id) ON DELETE SET NULL,
            assigned_appointment_id UUID REFERENCES appointments(id) ON DELETE SET NULL,
            amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            platform_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            business_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            notes TEXT,
            settled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_appointment_debts_user_status "
        "ON appointment_debts (user_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_ledger (
            id UUID PRIMARY KEY,
            restaurant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            appointment_id UUID REFERENCES appointments(id) ON DELETE SET NULL,
            kind VARCHAR(10) NOT NULL,
            amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            notes TEXT,
            settled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_business_ledger_restaurant_status "
        "ON business_ledger (restaurant_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS business_ledger")
    op.execute("DROP TABLE IF EXISTS appointment_debts")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS refund_amount")
