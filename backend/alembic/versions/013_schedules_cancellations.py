"""restaurant schedules, cancellation policy and business settings

Revision ID: 013
Revises: 012
Create Date: 2026-11-06
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def _add_col(table: str, col_name: str, col_type: str, default: str | None = None, nullable: bool = True):
    stmt = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col_name}" {col_type}'
    if default is not None:
        stmt += f" DEFAULT {default}"
    if not nullable:
        stmt += " NOT NULL"
    op.execute(stmt)


def upgrade():
    # ── Weekly opening hours ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS restaurant_schedules (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            restaurant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            day_of_week INTEGER NOT NULL,
            open_time TIME NOT NULL,
            close_time TIME NOT NULL,
            is_closed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_restaurant_schedules_restaurant "
        "ON restaurant_schedules (restaurant_id, day_of_week)"
    )
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_restaurant_schedules_day'
            ) THEN
                ALTER TABLE restaurant_schedules
                ADD CONSTRAINT ck_restaurant_schedules_day
                CHECK (day_of_week BETWEEN 0 AND 6);
            END IF;
        END $$;
    """)

    # ── Cancellation / refund audit on orders ──
    _add_col("orders", "cancelled_at", "TIMESTAMPTZ")
    _add_col("orders", "cancelled_by", "UUID REFERENCES users(id)")
    _add_col("orders", "cancellation_reason", "TEXT")
    _add_col("orders", "refund_amount", "DECIMAL(10,2)", default="0", nullable=False)
    _add_col("orders", "refund_status", "VARCHAR(20)", default="'none'", nullable=False)

    # ── Business settings defaults ──
    defaults = [
        ("APP_COMMISSION_PERCENTAGE", "15.0", "Porcentaje de comisión que absorbe el restaurante"),
        ("APP_FLAT_USAGE_FEE", "5.0", "Cuota fija por uso de la plataforma (la paga el cliente)"),
        ("DELIVERY_BASE_FEE", "20.0", "Tarifa base de envío"),
        ("DELIVERY_FREE_RADIUS_KM", "6", "Radio en km incluido en la tarifa base"),
        ("DELIVERY_EXTRA_FEE_PER_KM", "5.0", "Costo por km adicional"),
        ("MANDADO_PLATFORM_FEE", "10.0", "Comisión de la plataforma por mandado"),
        ("MANDADO_RISK_FEE_TYPE", "percentage", "Tipo de extra por riesgo: percentage o fixed"),
        ("MANDADO_RISK_PERCENTAGE", "10.0", "Porcentaje extra por riesgo en mandados"),
        ("MANDADO_RISK_FIXED_AMOUNT", "15.0", "Monto fijo extra por riesgo en mandados"),
        ("MANDADO_ACTIVE", "true", "Permitir mandados"),
        ("CANCELLATION_WINDOW_MIN", "5", "Minutos de gracia para cancelar un pedido confirmado"),
        ("CANCELLATION_REFUND_ENABLED", "true", "Generar reembolso al cancelar pedidos pagados"),
        ("RESTAURANT_TIMEZONE", "America/Mexico_City", "Zona horaria para horarios de restaurantes"),
        ("MP_ENABLED", "false", "Habilitar pagos con Mercado Pago"),
        ("TRANSFER_ENABLED", "false", "Habilitar pagos por transferencia"),
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
    # Shared settings are kept on downgrade on purpose: they may have been
    # edited by the operator and other features still read them.
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS refund_status")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS refund_amount")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS cancellation_reason")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS cancelled_by")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS cancelled_at")
    op.execute("DROP TABLE IF EXISTS restaurant_schedules CASCADE")
