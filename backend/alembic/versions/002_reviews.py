"""add reviews table

Revision ID: 002
Revises: 001
Create Date: 2026-06-02
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            order_id UUID NOT NULL REFERENCES orders(id),
            user_id UUID NOT NULL REFERENCES users(id),
            restaurant_id UUID REFERENCES restaurants(id),
            delivery_person_id UUID REFERENCES delivery_persons(id),
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_reviews_restaurant ON reviews (restaurant_id)")
    op.execute("CREATE INDEX idx_reviews_delivery_person ON reviews (delivery_person_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS reviews CASCADE")
