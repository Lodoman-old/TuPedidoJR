"""audit log for administrative actions

Revision ID: 025
Revises: 024
Create Date: 2026-11-10
"""
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            action VARCHAR(100) NOT NULL,
            entity VARCHAR(50),
            entity_id VARCHAR(100),
            detail JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs (created_at DESC)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
