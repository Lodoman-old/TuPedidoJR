"""Amplía las columnas de banco CEP para aceptar nombres de apiCEP.

Revision ID: 071
Revises: 070
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "orders",
        "cep_sender_bank",
        existing_type=sa.String(5),
        type_=sa.String(80),
        existing_nullable=True,
    )
    op.alter_column(
        "orders",
        "cep_receiver_bank",
        existing_type=sa.String(5),
        type_=sa.String(80),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "orders",
        "cep_receiver_bank",
        existing_type=sa.String(80),
        type_=sa.String(5),
        existing_nullable=True,
    )
    op.alter_column(
        "orders",
        "cep_sender_bank",
        existing_type=sa.String(80),
        type_=sa.String(5),
        existing_nullable=True,
    )
