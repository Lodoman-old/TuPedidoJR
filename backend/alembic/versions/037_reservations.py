"""reservaciones con deposito y prepedido

Revision ID: 037
Revises: 036
Create Date: 2026-11-13
"""
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS reservations_enabled "
        "BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS reservation_deposit_percent "
        "NUMERIC(5,2) NOT NULL DEFAULT 20"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS reservation_min_advance_min "
        "INTEGER NOT NULL DEFAULT 120"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS reservation_late_tolerance_min "
        "INTEGER NOT NULL DEFAULT 60"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reservations (
            id UUID PRIMARY KEY,
            restaurant_id UUID NOT NULL REFERENCES restaurants(id),
            user_id UUID NOT NULL REFERENCES users(id),
            reservation_at TIMESTAMPTZ NOT NULL,
            party_size INTEGER NOT NULL DEFAULT 2,
            status VARCHAR(30) NOT NULL DEFAULT 'requested',
            notes TEXT,
            preorder_items JSONB,
            preorder_subtotal NUMERIC(10,2) NOT NULL DEFAULT 0,
            service_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            service_fee_cash BOOLEAN NOT NULL DEFAULT FALSE,
            service_fee_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            deposit_percent NUMERIC(5,2) NOT NULL DEFAULT 20,
            deposit_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            deposit_status VARCHAR(20) NOT NULL DEFAULT 'not_required',
            deposit_method VARCHAR(20),
            deposit_proof_url TEXT,
            commission_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            commission_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            remaining_to_charge NUMERIC(10,2) NOT NULL DEFAULT 0,
            deposit_settlement_status VARCHAR(20) NOT NULL DEFAULT 'not_required',
            confirmed_at TIMESTAMPTZ,
            seated_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ,
            no_show_at TIMESTAMPTZ,
            cancelled_by UUID REFERENCES users(id),
            cancellation_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS service_fee_status "
        "VARCHAR(20) NOT NULL DEFAULT 'pending'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reservations_restaurant_at "
        "ON reservations (restaurant_id, reservation_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reservations_user_at "
        "ON reservations (user_id, reservation_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reservations_deposit_status "
        "ON reservations (deposit_status, deposit_settlement_status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reservations")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS reservation_late_tolerance_min")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS reservation_min_advance_min")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS reservation_deposit_percent")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS reservations_enabled")
