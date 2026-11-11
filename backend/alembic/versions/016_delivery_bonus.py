"""per-courier delivery bonus

Revision ID: 016
Revises: 015
Create Date: 2026-11-09
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE delivery_persons
        ADD COLUMN IF NOT EXISTS delivery_bonus_per_order DECIMAL(10,2)
        NOT NULL DEFAULT 0
    """)


def downgrade():
    op.execute(
        "ALTER TABLE delivery_persons DROP COLUMN IF EXISTS delivery_bonus_per_order"
    )
