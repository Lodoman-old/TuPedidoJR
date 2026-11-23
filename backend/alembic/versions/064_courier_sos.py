"""Alertas de auxilio de repartidores.

Revision ID: 064
Revises: 063
Create Date: 2026-11-22
"""
from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS courier_sos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            courier_id UUID NOT NULL REFERENCES delivery_persons(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
            lat DOUBLE PRECISION,
            lng DOUBLE PRECISION,
            message TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            resolved_at TIMESTAMPTZ,
            resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_courier_sos_status "
        "ON courier_sos (status, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS courier_sos")
