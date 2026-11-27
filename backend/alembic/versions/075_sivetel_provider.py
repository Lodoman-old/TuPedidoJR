"""Datos del proveedor Sivetel para recargas.

Revision ID: 075
Revises: 074
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recarga_orders",
        sa.Column("provider_request_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "recarga_orders",
        sa.Column("provider_folio", sa.String(40), nullable=True),
    )
    op.add_column(
        "recarga_orders",
        sa.Column(
            "provider_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "recarga_orders",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_recarga_orders_provider_request_id",
        "recarga_orders",
        ["provider_request_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recarga_orders_provider_request_id",
        table_name="recarga_orders",
    )
    op.drop_column("recarga_orders", "last_attempt_at")
    op.drop_column("recarga_orders", "provider_attempts")
    op.drop_column("recarga_orders", "provider_folio")
    op.drop_column("recarga_orders", "provider_request_id")
