"""server-side cart snapshot per user

Revision ID: 023
Revises: 022
Create Date: 2026-11-10
"""
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_carts (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            restaurant_id UUID REFERENCES restaurants(id) ON DELETE SET NULL,
            payload JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS user_carts CASCADE")
