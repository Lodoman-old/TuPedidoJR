"""Verificación de teléfono de usuarios.

Revision ID: 067
Revises: 066
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "phone_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("users", "phone_verified", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "phone_verified")
