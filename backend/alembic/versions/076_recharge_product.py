"""Producto exacto de Sivetel en recargas.

Revision ID: 076
Revises: 075
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("recharge_product_code", sa.String(30), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("recharge_product_description", sa.String(200), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("recharge_kind", sa.String(20), nullable=True),
    )
    op.add_column(
        "recarga_orders",
        sa.Column("product_code", sa.String(30), nullable=True),
    )
    op.add_column(
        "recarga_orders",
        sa.Column("product_description", sa.String(200), nullable=True),
    )
    op.add_column(
        "recarga_orders",
        sa.Column("product_kind", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recarga_orders", "product_kind")
    op.drop_column("recarga_orders", "product_description")
    op.drop_column("recarga_orders", "product_code")
    op.drop_column("orders", "recharge_kind")
    op.drop_column("orders", "recharge_product_description")
    op.drop_column("orders", "recharge_product_code")
