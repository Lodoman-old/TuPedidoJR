"""add push_tokens table for FCM registration tokens

Revision ID: 012
Revises: 011
Create Date: 2026-11-05
"""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS push_tokens (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token VARCHAR(512) NOT NULL,
            platform VARCHAR(20) NOT NULL DEFAULT 'web',
            device_label VARCHAR(150),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_push_tokens_token UNIQUE (token)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_push_tokens_user ON push_tokens (user_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS push_tokens CASCADE")
