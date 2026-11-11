"""loyalty points and referrals

Revision ID: 026
Revises: 025
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS loyalty_points INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(20)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by UUID REFERENCES users(id)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_bonus_awarded BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("""
        UPDATE users SET referral_code = upper(substr(md5(id::text), 1, 8))
        WHERE referral_code IS NULL
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users (referral_code)")

    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS points_redeemed INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS loyalty_discount DECIMAL(10,2) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS points_awarded BOOLEAN NOT NULL DEFAULT FALSE")

    defaults = [
        ("LOYALTY_ENABLED", "true", "Activar puntos de lealtad"),
        ("LOYALTY_POINTS_PER_100", "5", "Puntos otorgados por cada $100 de compra"),
        ("LOYALTY_VALUE_PER_POINT", "1.0", "Valor en pesos de cada punto"),
        ("REFERRAL_BONUS_POINTS", "50", "Puntos para quien invita y para el invitado"),
    ]
    for key, value, description in defaults:
        op.execute(
            sa.text(
                """
                INSERT INTO settings (id, key, value, description, created_at, updated_at)
                SELECT uuid_generate_v4(), :key, :value, :description, NOW(), NOW()
                WHERE NOT EXISTS (SELECT 1 FROM settings WHERE key = :key)
                """
            ).bindparams(key=key, value=value, description=description)
        )


def downgrade():
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS points_awarded")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS loyalty_discount")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS points_redeemed")
    op.execute("DROP INDEX IF EXISTS idx_users_referral_code")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS referral_bonus_awarded")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS referred_by")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS referral_code")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS loyalty_points")
