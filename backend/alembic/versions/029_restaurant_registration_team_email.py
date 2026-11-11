"""restaurant self-registration, team users and email settings

Revision ID: 029
Revises: 028
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE restaurants
        ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'
    """)
    op.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS rejection_reason TEXT")
    op.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ")
    op.execute("""
        ALTER TABLE restaurants
        ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id) ON DELETE SET NULL
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS restaurant_users (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            restaurant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL DEFAULT 'staff',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_restaurant_user UNIQUE (restaurant_id, user_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_restaurant_users_user
        ON restaurant_users (user_id)
    """)
    op.execute("""
        INSERT INTO restaurant_users (restaurant_id, user_id, role, is_active)
        SELECT r.id, r.owner_id, 'owner', TRUE
        FROM restaurants r
        WHERE NOT EXISTS (
            SELECT 1 FROM restaurant_users ru
            WHERE ru.restaurant_id = r.id AND ru.user_id = r.owner_id
        )
    """)

    defaults = [
        ("EMAIL_ENABLED", "false", "Activar envío de correos del sistema"),
        ("SMTP_HOST", "", "Servidor SMTP. Ej. smtp.gmail.com o smtp.resend.com"),
        ("SMTP_PORT", "587", "Puerto SMTP. Normalmente 587 o 465"),
        ("SMTP_USERNAME", "", "Usuario SMTP"),
        ("SMTP_PASSWORD", "", "Contraseña o API key SMTP"),
        ("SMTP_USE_TLS", "true", "Usar STARTTLS en el puerto 587"),
        ("SMTP_USE_SSL", "false", "Usar SSL directo en el puerto 465"),
        ("SMTP_FROM_NAME", "TuPedidoJR", "Nombre del remitente"),
        ("SMTP_FROM_EMAIL", "", "Correo remitente"),
        ("APP_PUBLIC_URL", "http://localhost:8080", "URL pública de la plataforma"),
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
    for key, _, _ in [
        ("EMAIL_ENABLED", "", ""), ("SMTP_HOST", "", ""), ("SMTP_PORT", "", ""),
        ("SMTP_USERNAME", "", ""), ("SMTP_PASSWORD", "", ""),
        ("SMTP_USE_TLS", "", ""), ("SMTP_USE_SSL", "", ""),
        ("SMTP_FROM_NAME", "", ""), ("SMTP_FROM_EMAIL", "", ""),
        ("APP_PUBLIC_URL", "", ""),
    ]:
        op.execute(sa.text("DELETE FROM settings WHERE key = :key").bindparams(key=key))
    op.execute("DROP TABLE IF EXISTS restaurant_users CASCADE")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS approved_by")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS approved_at")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS rejection_reason")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS status")
