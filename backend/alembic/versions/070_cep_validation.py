"""Validación CEP de transferencias SPEI.

Revision ID: 070
Revises: 069
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("transfer_tracking_key", sa.String(30), nullable=True),
    )
    op.add_column("orders", sa.Column("cep_status", sa.String(20), nullable=True))
    op.add_column(
        "orders",
        sa.Column("cep_validated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("orders", sa.Column("cep_sender_bank", sa.String(5), nullable=True))
    op.add_column(
        "orders", sa.Column("cep_receiver_bank", sa.String(5), nullable=True)
    )
    op.add_column(
        "orders",
        sa.Column(
            "cep_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_orders_transfer_tracking_key",
        "orders",
        ["transfer_tracking_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_transfer_tracking_key", table_name="orders")
    op.drop_column("orders", "cep_payload")
    op.drop_column("orders", "cep_receiver_bank")
    op.drop_column("orders", "cep_sender_bank")
    op.drop_column("orders", "cep_validated_at")
    op.drop_column("orders", "cep_status")
    op.drop_column("orders", "transfer_tracking_key")
