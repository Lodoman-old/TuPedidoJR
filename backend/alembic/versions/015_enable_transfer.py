"""enable bank transfer payments (Mercado Pago stays disabled)

Revision ID: 015
Revises: 014
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO settings (id, key, value, description, created_at, updated_at)
        SELECT uuid_generate_v4(), 'TRANSFER_ENABLED', 'true',
               'Habilitar pagos por transferencia bancaria', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM settings WHERE key = 'TRANSFER_ENABLED')
    """)
    op.execute("""
        UPDATE settings SET value = 'true', updated_at = NOW()
        WHERE key = 'TRANSFER_ENABLED'
    """)
    op.execute("""
        UPDATE settings SET value = 'false', updated_at = NOW()
        WHERE key = 'MP_ENABLED'
    """)


def downgrade():
    op.execute("""
        UPDATE settings SET value = 'false', updated_at = NOW()
        WHERE key = 'TRANSFER_ENABLED'
    """)
