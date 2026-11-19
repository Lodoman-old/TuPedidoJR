"""pagos en linea de citas (transferencia y validacion)

Revision ID: 050
Revises: 049
Create Date: 2026-11-19
"""
from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "online_amount NUMERIC(10,2) NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "cash_due NUMERIC(10,2) NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "business_credit NUMERIC(10,2) NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "business_debt NUMERIC(10,2) NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "deposit_percent NUMERIC(5,2) NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "payment_reference VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS "
        "receipt_status VARCHAR(20) NOT NULL DEFAULT 'none'"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ"
    )
    # Citas existentes: se crearon en efectivo, el negocio debe la comision.
    op.execute(
        "UPDATE appointments SET cash_due = price + 5, business_debt = 10 "
        "WHERE payment_mode = 'cash' AND cash_due = 0"
    )


def downgrade() -> None:
    for column in (
        "online_amount", "cash_due", "business_credit", "business_debt",
        "deposit_percent", "payment_reference", "receipt_status", "paid_at",
    ):
        op.execute(f"ALTER TABLE appointments DROP COLUMN IF EXISTS {column}")
