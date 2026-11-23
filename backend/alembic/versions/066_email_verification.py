"""Verificación de correo de usuarios.

Revision ID: 066
Revises: 065
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Las cuentas que ya existen se consideran verificadas para no bloquearlas.
    op.execute("UPDATE users SET email_verified = true, email_verified_at = now()")
    op.alter_column("users", "email_verified", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
