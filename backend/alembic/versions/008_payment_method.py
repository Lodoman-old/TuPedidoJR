"""add payment_method to orders

Revision ID: 008
Revises: 007
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"


def upgrade():
    op.add_column(
        "orders",
        sa.Column("payment_method", sa.String(10), server_default="mp", nullable=False),
    )


def downgrade():
    op.drop_column("orders", "payment_method")
