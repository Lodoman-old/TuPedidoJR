"""add saved_addresses table

Revision ID: 005
Revises: 004
Create Date: 2026-06-02
"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS saved_addresses (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            address TEXT NOT NULL,
            location GEOGRAPHY(POINT, 4326) NOT NULL,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            notes VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_saved_addresses_user ON saved_addresses (user_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS saved_addresses CASCADE")
