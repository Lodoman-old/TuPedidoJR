"""add preparation_base_time_min to restaurants

Revision ID: 007
Revises: 006
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"


def upgrade():
    op.add_column(
        "restaurants",
        sa.Column("preparation_base_time_min", sa.Integer(), server_default="10", nullable=False),
    )


def downgrade():
    op.drop_column("restaurants", "preparation_base_time_min")
