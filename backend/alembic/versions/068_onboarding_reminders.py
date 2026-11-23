"""Recordatorios de onboarding para negocios.

Revision ID: 068
Revises: 067
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "restaurants",
        sa.Column("onboarding_reminder_2_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "restaurants",
        sa.Column("onboarding_reminder_7_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("restaurants", "onboarding_reminder_7_at")
    op.drop_column("restaurants", "onboarding_reminder_2_at")
