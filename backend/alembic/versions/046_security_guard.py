"""eventos de seguridad e IPs bloqueadas

Revision ID: 046
Revises: 045
Create Date: 2026-11-16
"""
from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_events (
            id UUID PRIMARY KEY,
            ip VARCHAR(64) NOT NULL,
            kind VARCHAR(40) NOT NULL,
            path VARCHAR(400),
            method VARCHAR(10),
            user_agent VARCHAR(400),
            detail TEXT,
            blocked BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_security_events_created ON security_events (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_security_events_ip ON security_events (ip, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_security_events_kind ON security_events (kind, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_ips (
            id UUID PRIMARY KEY,
            ip VARCHAR(64) NOT NULL UNIQUE,
            reason VARCHAR(40) NOT NULL DEFAULT 'auto',
            detail TEXT,
            path VARCHAR(400),
            auto BOOLEAN NOT NULL DEFAULT TRUE,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_blocked_ips_ip ON blocked_ips (ip)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_blocked_ips_expires ON blocked_ips (expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS blocked_ips")
    op.execute("DROP TABLE IF EXISTS security_events")
