"""restaurant cuisine (giro) for search

Revision ID: 014
Revises: 013
Create Date: 2026-11-06
"""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS cuisine VARCHAR(100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_restaurants_cuisine ON restaurants (cuisine)"
    )
    # Seed the demo/local data with a sensible giro so search works right away.
    op.execute("""
        UPDATE restaurants SET cuisine = 'Pizza'
        WHERE cuisine IS NULL
          AND (name ILIKE '%pizza%' OR description ILIKE '%pizza%')
    """)
    op.execute("""
        UPDATE restaurants SET cuisine = 'Sushi'
        WHERE cuisine IS NULL
          AND (name ILIKE '%sushi%' OR description ILIKE '%sushi%'
               OR description ILIKE '%japon%')
    """)
    op.execute("""
        UPDATE restaurants SET cuisine = 'Tacos'
        WHERE cuisine IS NULL
          AND (name ILIKE '%taco%' OR name ILIKE '%taquer%'
               OR description ILIKE '%taco%')
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_restaurants_cuisine")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS cuisine")
