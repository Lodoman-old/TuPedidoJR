"""validacion de comprobantes con IA (solo grado de certeza)

Revision ID: 043
Revises: 042
Create Date: 2026-11-15
"""
from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS receipt_validations (
            id UUID PRIMARY KEY,
            entity_type VARCHAR(30) NOT NULL,
            entity_id UUID NOT NULL,
            file_url TEXT NOT NULL,
            expected_kind VARCHAR(20) NOT NULL,
            expected_amount NUMERIC(10,2),
            expected_date TIMESTAMPTZ,
            expected_recipient VARCHAR(250),
            document_type VARCHAR(30),
            confidence INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(15) NOT NULL DEFAULT 'review',
            extracted JSONB,
            issues JSONB,
            summary TEXT,
            provider VARCHAR(20) NOT NULL DEFAULT 'gemini',
            model VARCHAR(60),
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_receipt_validations_entity "
        "ON receipt_validations (entity_type, entity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_receipt_validations_confidence "
        "ON receipt_validations (confidence)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS receipt_validations")
