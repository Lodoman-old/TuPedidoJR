"""pedidos especiales opcionales en restaurantes

Los restaurantes dejan de mostrar solicitudes por defecto. El dueño puede
activarlas desde Perfil del negocio. Las tiendas conservan el flujo siempre.

Revision ID: 042
Revises: 041
Create Date: 2026-11-14
"""
from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE restaurants SET accepts_custom_requests = FALSE "
        "WHERE business_type = 'restaurant' AND accepts_custom_requests = TRUE"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE restaurants SET accepts_custom_requests = TRUE "
        "WHERE business_type = 'restaurant' AND accepts_custom_requests = FALSE"
    )
