"""tips, public restaurant pages and support settings

Revision ID: 018
Revises: 017
Create Date: 2026-11-10
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS tip_amount DECIMAL(10,2) NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE restaurants
        ADD COLUMN IF NOT EXISTS slug VARCHAR(120)
    """)
    op.execute("""
        ALTER TABLE restaurants
        ADD COLUMN IF NOT EXISTS public_page_enabled BOOLEAN NOT NULL DEFAULT TRUE
    """)
    op.execute("""
        UPDATE restaurants
        SET slug = trim(both '-' from lower(regexp_replace(
            translate(name, 'áéíóúüÁÉÍÓÚÜñÑ', 'aeiouuAEIOUUnN'),
            '[^a-zA-Z0-9]+', '-', 'g'
        )))
        WHERE slug IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_restaurants_slug
        ON restaurants (slug)
    """)
    op.execute("""
        INSERT INTO settings (id, key, value, description, created_at, updated_at)
        SELECT uuid_generate_v4(), 'WHATSAPP_SUPPORT', '',
               'Número de WhatsApp de soporte con lada país (ej. 524121234567)', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM settings WHERE key = 'WHATSAPP_SUPPORT')
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_restaurants_slug")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS public_page_enabled")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS slug")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS tip_amount")
