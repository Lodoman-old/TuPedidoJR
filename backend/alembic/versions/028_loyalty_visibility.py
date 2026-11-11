"""loyalty visibility setting

Revision ID: 028
Revises: 027
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            """
            INSERT INTO settings (id, key, value, description, created_at, updated_at)
            SELECT uuid_generate_v4(), :key, :value, :description, NOW(), NOW()
            WHERE NOT EXISTS (SELECT 1 FROM settings WHERE key = :key)
            """
        ).bindparams(
            key="LOYALTY_VISIBLE",
            value="true",
            description="Mostrar puntos y referidos en la web y la app",
        )
    )


def downgrade():
    op.execute("DELETE FROM settings WHERE key = 'LOYALTY_VISIBLE'")
