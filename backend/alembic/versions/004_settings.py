"""add settings table

Revision ID: 004
Revises: 003
Create Date: 2026-06-02
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            key VARCHAR(255) NOT NULL UNIQUE,
            value TEXT,
            description VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_settings_key ON settings (key)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS settings CASCADE")
