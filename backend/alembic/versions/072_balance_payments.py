"""Pagos del saldo pendiente de clientes.

Revision ID: 072
Revises: 071
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "balance_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("transfer_tracking_key", sa.String(30), nullable=True),
        sa.Column("cep_status", sa.String(20), nullable=True),
        sa.Column(
            "cep_validated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("cep_sender_bank", sa.String(80), nullable=True),
        sa.Column("cep_receiver_bank", sa.String(80), nullable=True),
        sa.Column(
            "cep_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_balance_payments_user_id",
        "balance_payments",
        ["user_id"],
    )
    op.create_index(
        "ix_balance_payments_status",
        "balance_payments",
        ["status"],
    )
    op.create_index(
        "ix_balance_payments_transfer_tracking_key",
        "balance_payments",
        ["transfer_tracking_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_balance_payments_transfer_tracking_key",
        table_name="balance_payments",
    )
    op.drop_index("ix_balance_payments_status", table_name="balance_payments")
    op.drop_index("ix_balance_payments_user_id", table_name="balance_payments")
    op.drop_table("balance_payments")
