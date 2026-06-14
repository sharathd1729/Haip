"""Dograh voice AI integration

Revision ID: 025
Revises: 024
Create Date: 2026-06-08

Adds Dograh-specific columns to calls and tenants tables.
Does NOT modify existing columns — additive only.
"""
import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── calls table — Dograh columns ─────────────────────────────────────────
    op.add_column("calls", sa.Column(
        "voice_platform",
        sa.String(20),
        nullable=False,
        server_default="callerdesk",
    ))
    op.add_column("calls", sa.Column("dograh_call_id", sa.String(255), nullable=True))
    op.add_column("calls", sa.Column("dograh_agent_id", sa.String(255), nullable=True))
    op.add_column("calls", sa.Column("sip_trunk_provider", sa.String(50), nullable=True))
    op.add_column("calls", sa.Column("transfer_to_human", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("calls", sa.Column("transfer_reason", sa.String(255), nullable=True))

    # Unique constraint on dograh_call_id (guards idempotency at DB level)
    op.create_unique_constraint("uq_calls_dograh_call_id", "calls", ["dograh_call_id"])

    # Partial index: only index non-null dograh_call_id rows (Postgres partial index)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_calls_dograh_call_id
        ON calls (dograh_call_id)
        WHERE dograh_call_id IS NOT NULL
    """)

    # ── tenants table — Dograh + voice platform config ────────────────────────
    op.add_column("tenants", sa.Column("dograh_agent_id", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column(
        "dograh_webhook_secret_enc",
        sa.LargeBinary,
        nullable=True,
    ))
    op.add_column("tenants", sa.Column(
        "voice_platform",
        sa.String(50),
        nullable=True,
        server_default="callerdesk",
    ))
    op.add_column("tenants", sa.Column("sip_trunk_provider", sa.String(50), nullable=True))
    op.add_column("tenants", sa.Column("sip_trunk_number", sa.String(20), nullable=True))


def downgrade() -> None:
    # ── tenants ───────────────────────────────────────────────────────────────
    op.drop_column("tenants", "sip_trunk_number")
    op.drop_column("tenants", "sip_trunk_provider")
    op.drop_column("tenants", "voice_platform")
    op.drop_column("tenants", "dograh_webhook_secret_enc")
    op.drop_column("tenants", "dograh_agent_id")

    # ── calls ─────────────────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS ix_calls_dograh_call_id")
    op.drop_constraint("uq_calls_dograh_call_id", "calls", type_="unique")
    op.drop_column("calls", "transfer_reason")
    op.drop_column("calls", "transfer_to_human")
    op.drop_column("calls", "sip_trunk_provider")
    op.drop_column("calls", "dograh_agent_id")
    op.drop_column("calls", "dograh_call_id")
    op.drop_column("calls", "voice_platform")
