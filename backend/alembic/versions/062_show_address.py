"""opcion para ocultar el domicilio del negocio en su pagina publica

Revision ID: 062
Revises: 061
Create Date: 2026-11-22
"""
from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "show_address BOOLEAN NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS show_address")
