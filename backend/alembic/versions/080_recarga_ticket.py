"""Ticket de recarga enviado al cliente.

Revision ID: 080
Revises: 079
Create Date: 2026-11-27
"""
import sqlalchemy as sa
from alembic import op

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recarga_orders",
        sa.Column("ticket_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recarga_orders", "ticket_sent_at")
