"""Los cupones se eliminan con su negocio.

Revision ID: 065
Revises: 064
Create Date: 2026-11-22
"""
from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE coupons DROP CONSTRAINT IF EXISTS coupons_restaurant_id_fkey"
    )
    op.execute(
        "ALTER TABLE coupons ADD CONSTRAINT coupons_restaurant_id_fkey "
        "FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE coupons DROP CONSTRAINT IF EXISTS coupons_restaurant_id_fkey"
    )
    op.execute(
        "ALTER TABLE coupons ADD CONSTRAINT coupons_restaurant_id_fkey "
        "FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)"
    )
