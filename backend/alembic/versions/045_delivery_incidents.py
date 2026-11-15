"""incidencias de entrega, deuda del cliente y ajustes a negocios

Revision ID: 045
Revises: 044
Create Date: 2026-11-15
"""
from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS pending_balance NUMERIC(10,2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS pending_installments INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS installment_amount NUMERIC(10,2) NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS debt_charged NUMERIC(10,2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS redelivery_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS incident_id UUID
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS delivery_incidents (
            id UUID PRIMARY KEY,
            entity_type VARCHAR(20) NOT NULL,
            entity_id UUID NOT NULL,
            restaurant_id UUID,
            customer_id UUID,
            courier_id UUID,
            reason_code VARCHAR(30) NOT NULL,
            notes TEXT,
            photo_url TEXT,
            lat DOUBLE PRECISION,
            lng DOUBLE PRECISION,
            item_kind VARCHAR(20) NOT NULL DEFAULT 'food',
            status VARCHAR(20) NOT NULL DEFAULT 'reported',
            product_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            delivery_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            redelivery_fee NUMERIC(10,2) NOT NULL DEFAULT 0,
            courier_pay NUMERIC(10,2) NOT NULL DEFAULT 0,
            business_pay NUMERIC(10,2) NOT NULL DEFAULT 0,
            customer_refund NUMERIC(10,2) NOT NULL DEFAULT 0,
            customer_debt NUMERIC(10,2) NOT NULL DEFAULT 0,
            platform_cost NUMERIC(10,2) NOT NULL DEFAULT 0,
            requires_authorization BOOLEAN NOT NULL DEFAULT FALSE,
            approved_by UUID,
            approved_at TIMESTAMPTZ,
            resolution_notes TEXT,
            custody_code VARCHAR(12),
            custody_at TIMESTAMPTZ,
            custody_photo_url TEXT,
            holding_until TIMESTAMPTZ,
            redelivery_at TIMESTAMPTZ,
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_delivery_incidents_status
            ON delivery_incidents (status, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_delivery_incidents_entity
            ON delivery_incidents (entity_type, entity_id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS restaurant_adjustments (
            id UUID PRIMARY KEY,
            restaurant_id UUID NOT NULL,
            incident_id UUID,
            kind VARCHAR(10) NOT NULL DEFAULT 'credit',
            amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            description TEXT,
            settled BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_restaurant_adjustments_restaurant
            ON restaurant_adjustments (restaurant_id, settled)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS restaurant_adjustments")
    op.execute("DROP TABLE IF EXISTS delivery_incidents")
    op.execute(
        """
        ALTER TABLE orders
            DROP COLUMN IF EXISTS debt_charged,
            DROP COLUMN IF EXISTS redelivery_fee,
            DROP COLUMN IF EXISTS incident_id
        """
    )
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS pending_balance,
            DROP COLUMN IF EXISTS pending_installments,
            DROP COLUMN IF EXISTS installment_amount
        """
    )
