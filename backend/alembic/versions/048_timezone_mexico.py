"""zona horaria de la base en hora de México

Revision ID: 048
Revises: 047
Create Date: 2026-11-17

Los timestamps se guardan como timestamptz (UTC internamente). Este ajuste hace
que las sesiones de la base trabajen con la zona de México, para que
``now()``, ``date_trunc`` y ``::date`` coincidan con el día local.
"""
from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format(
                'ALTER DATABASE %I SET timezone TO ''America/Mexico_City''',
                current_database()
            );
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format(
                'ALTER DATABASE %I SET timezone TO ''UTC''',
                current_database()
            );
        END
        $$;
        """
    )
