"""Pedidos programados y apoyo de reparto.

Revision ID: 079
Revises: 078
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "scheduled_outside_hours",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "orders",
        sa.Column("scheduled_approval_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "scheduled_approval_deadline",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("scheduled_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "scheduled_prep_ack",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "orders",
        sa.Column("scheduled_prep_ack_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "scheduled_reminder_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "courier_support_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "courier_support_fee",
            sa.DECIMAL(10, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "courier_support_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "courier_support_alert_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_orders_scheduled_for",
        "orders",
        ["scheduled_for"],
    )
    op.create_index(
        "ix_orders_scheduled_approval_deadline",
        "orders",
        ["scheduled_approval_deadline"],
    )
    op.create_index(
        "ix_orders_scheduled_reminder_sent_at",
        "orders",
        ["scheduled_reminder_sent_at"],
    )
    op.create_index(
        "ix_orders_courier_support_alert_at",
        "orders",
        ["courier_support_alert_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_courier_support_alert_at", table_name="orders")
    op.drop_index("ix_orders_scheduled_reminder_sent_at", table_name="orders")
    op.drop_index("ix_orders_scheduled_approval_deadline", table_name="orders")
    op.drop_index("ix_orders_scheduled_for", table_name="orders")
    op.drop_column("orders", "courier_support_alert_at")
    op.drop_column("orders", "courier_support_requested_at")
    op.drop_column("orders", "courier_support_fee")
    op.drop_column("orders", "courier_support_requested")
    op.drop_column("orders", "scheduled_reminder_sent_at")
    op.drop_column("orders", "scheduled_prep_ack_at")
    op.drop_column("orders", "scheduled_prep_ack")
    op.drop_column("orders", "scheduled_approved_at")
    op.drop_column("orders", "scheduled_approval_deadline")
    op.drop_column("orders", "scheduled_approval_status")
    op.drop_column("orders", "scheduled_outside_hours")
