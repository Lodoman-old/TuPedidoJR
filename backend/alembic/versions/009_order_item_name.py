"""add name column to order_items

Revision ID: 009
Revises: 008
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"


def upgrade():
    op.add_column(
        "order_items",
        sa.Column("name", sa.String(150), nullable=False, server_default=""),
    )
    op.alter_column("order_items", "name", server_default=None)


def downgrade():
    op.drop_column("order_items", "name")
