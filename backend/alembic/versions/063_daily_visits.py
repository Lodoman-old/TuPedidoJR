"""Visitas diarias para métricas de audiencia y publicidad.

Revision ID: 063
Revises: 062
Create Date: 2026-11-22
"""
from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_visits (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            visited_on DATE NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL DEFAULT 'customer',
            views INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_daily_visits_user_day UNIQUE (visited_on, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_daily_visits_day_role "
        "ON daily_visits (visited_on, role)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS daily_visits")
