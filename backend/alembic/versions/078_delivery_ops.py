"""Operación de reparto sin repartidores.

Revision ID: 078
Revises: 077
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "no_courier_hold",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "orders",
        sa.Column("no_courier_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "no_courier_decision_deadline",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("courier_alert_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "near_closing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "business_confirmation_deadline",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "admin_delivery",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "admin_delivery_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_orders_admin_delivery_by_users",
        "orders",
        "users",
        ["admin_delivery_by"],
        ["id"],
    )
    op.create_index(
        "ix_orders_courier_alert_at",
        "orders",
        ["courier_alert_at"],
    )
    op.create_index(
        "ix_orders_no_courier_decision_deadline",
        "orders",
        ["no_courier_decision_deadline"],
    )
    op.create_index(
        "ix_orders_business_confirmation_deadline",
        "orders",
        ["business_confirmation_deadline"],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_business_confirmation_deadline", table_name="orders")
    op.drop_index("ix_orders_no_courier_decision_deadline", table_name="orders")
    op.drop_index("ix_orders_courier_alert_at", table_name="orders")
    op.drop_constraint(
        "fk_orders_admin_delivery_by_users",
        "orders",
        type_="foreignkey",
    )
    op.drop_column("orders", "admin_delivery_by")
    op.drop_column("orders", "admin_delivery")
    op.drop_column("orders", "business_confirmation_deadline")
    op.drop_column("orders", "near_closing")
    op.drop_column("orders", "courier_alert_at")
    op.drop_column("orders", "no_courier_decision_deadline")
    op.drop_column("orders", "no_courier_notified_at")
    op.drop_column("orders", "no_courier_hold")
    op.drop_column("orders", "ready_at")
