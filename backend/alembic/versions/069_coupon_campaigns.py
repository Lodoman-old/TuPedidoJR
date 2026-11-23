"""Campañas de cupones a clientes de un negocio.

Revision ID: 069
Revises: 068
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coupon_campaigns",
        sa.Column("coupon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channels", sa.String(50), nullable=False, server_default=""),
        sa.Column("audience_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("push_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("push_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("email_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("email_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_coupon_campaigns_coupon_id", "coupon_campaigns", ["coupon_id"]
    )
    op.create_index(
        "ix_coupon_campaigns_restaurant_id", "coupon_campaigns", ["restaurant_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_coupon_campaigns_restaurant_id", table_name="coupon_campaigns"
    )
    op.drop_index("ix_coupon_campaigns_coupon_id", table_name="coupon_campaigns")
    op.drop_table("coupon_campaigns")
