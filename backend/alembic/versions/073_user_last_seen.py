"""Última actividad de los usuarios.

Revision ID: 073
Revises: 072
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_last_seen_at",
        "users",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_last_seen_at", table_name="users")
    op.drop_column("users", "last_seen_at")
