"""Registro de accesos por IP y pantalla.

Revision ID: 081
Revises: 080
Create Date: 2026-11-27
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("screen", sa.String(length=120), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_access_logs_user_id", "access_logs", ["user_id"])
    op.create_index("ix_access_logs_ip", "access_logs", ["ip"])
    op.create_index("ix_access_logs_role", "access_logs", ["role"])
    op.create_index("ix_access_logs_screen", "access_logs", ["screen"])
    op.create_index("ix_access_logs_created_at", "access_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("access_logs")
