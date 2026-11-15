"""corte de repartidor con saldo neto (a favor o por entregar)

Revision ID: 044
Revises: 043
Create Date: 2026-11-15
"""
from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE delivery_payouts
            ADD COLUMN IF NOT EXISTS total_debt NUMERIC(10,2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS total_advances NUMERIC(10,2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS net_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS direction VARCHAR(15) NOT NULL DEFAULT 'to_courier'
        """
    )
    op.execute("UPDATE delivery_payouts SET net_amount = total_earnings WHERE net_amount = 0")

    op.execute(
        """
        ALTER TABLE delivery_persons
            ADD COLUMN IF NOT EXISTS pending_platform_credit NUMERIC(10,2) NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS courier_credit_applied BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    op.execute(
        """
        UPDATE orders SET courier_credit_applied = TRUE
        WHERE status = 'delivered'
          AND payment_method IN ('transfer', 'mp')
          AND payment_status IN ('approved', 'paid')
        """
    )
    op.execute(
        """
        UPDATE delivery_persons dp
        SET pending_platform_credit = GREATEST(
            COALESCE((
                SELECT SUM(o.delivery_earnings) FROM orders o
                WHERE o.delivery_person_id = dp.id
                  AND o.status = 'delivered'
                  AND o.payment_method IN ('transfer', 'mp')
                  AND o.payment_status IN ('approved', 'paid')
            ), 0)
            + COALESCE((
                SELECT SUM(s.courier_earnings) FROM shipments s
                WHERE s.delivery_person_id = dp.id
                  AND (
                      s.status = 'failed'
                      OR (s.status = 'delivered' AND COALESCE(s.amount_to_collect, 0) = 0)
                  )
            ), 0)
            - COALESCE((
                SELECT SUM(p.total_earnings) FROM delivery_payouts p
                WHERE p.delivery_person_id = dp.id AND p.status != 'cancelled'
            ), 0),
            0
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE orders
            DROP COLUMN IF EXISTS courier_credit_applied
        """
    )
    op.execute(
        """
        ALTER TABLE delivery_persons
            DROP COLUMN IF EXISTS pending_platform_credit
        """
    )
    op.execute(
        """
        ALTER TABLE delivery_payouts
            DROP COLUMN IF EXISTS total_debt,
            DROP COLUMN IF EXISTS total_advances,
            DROP COLUMN IF EXISTS net_amount,
            DROP COLUMN IF EXISTS direction
        """
    )
