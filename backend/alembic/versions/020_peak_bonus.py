"""peak-hour courier bonus settings

Revision ID: 020
Revises: 019
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    defaults = [
        ("PEAK_BONUS_ENABLED", "false", "Activar bono por hora pico"),
        ("PEAK_BONUS_START", "13:00", "Hora de inicio del bono (HH:MM)"),
        ("PEAK_BONUS_END", "15:00", "Hora de fin del bono (HH:MM)"),
        ("PEAK_BONUS_AMOUNT", "5.0", "Monto extra por entrega en hora pico"),
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
    for key in ("PEAK_BONUS_ENABLED", "PEAK_BONUS_START", "PEAK_BONUS_END", "PEAK_BONUS_AMOUNT"):
        op.execute(sa.text("DELETE FROM settings WHERE key = :key").bindparams(key=key))
