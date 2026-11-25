"""Recarga de tiempo aire dentro del pedido.

Revision ID: 074
Revises: 073
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("recharge_company", sa.String(40), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("recharge_phone", sa.String(20), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "recharge_amount",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "recharge_fee",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column("recharge_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "recarga_orders",
        sa.Column("origin", sa.String(20), nullable=True),
    )
    op.execute(
        "UPDATE recarga_orders SET origin = "
        "CASE WHEN payment_method = 'cash' THEN 'courier' ELSE 'portal' END "
        "WHERE origin IS NULL"
    )
    op.create_index("ix_recarga_orders_order_id", "recarga_orders", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_recarga_orders_order_id", table_name="recarga_orders")
    op.drop_column("recarga_orders", "origin")
    op.drop_column("orders", "recharge_status")
    op.drop_column("orders", "recharge_fee")
    op.drop_column("orders", "recharge_amount")
    op.drop_column("orders", "recharge_phone")
    op.drop_column("orders", "recharge_company")
