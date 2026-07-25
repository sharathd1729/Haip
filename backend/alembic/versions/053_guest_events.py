"""guest_events — unified guest-level activity ledger

Backing store for the Guest Journey view and, once dual-write is proven, for
leads_service.build_timeline() (which today unions messages + calls +
inquiry_stage_log in Python on every request).

Append-only. The unique constraint makes dual-writing from live code paths
idempotent against re-runs of the backfill.

Revision ID: 053
Revises: 052
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    if "guest_events" in _inspect(bind).get_table_names():
        return

    op.create_table(
        "guest_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("guest_id", sa.String(), nullable=True),
        sa.Column("inquiry_id", sa.String(), nullable=True),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("source_module", sa.String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("direction", sa.String(20), nullable=True),
        sa.Column("preview", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "entity_type", "entity_id", "event_type",
            name="uq_guest_events_dedup",
        ),
    )

    op.create_index("ix_guest_events_tenant_id", "guest_events", ["tenant_id"])
    op.create_index("ix_guest_events_guest_id", "guest_events", ["guest_id"])
    op.create_index("ix_guest_events_inquiry_id", "guest_events", ["inquiry_id"])
    # Guest Journey read path: newest-first per guest.
    op.execute("""
        CREATE INDEX ix_guest_events_tenant_guest_time
        ON guest_events (tenant_id, guest_id, occurred_at DESC)
    """)
    # Inquiry timeline read path (build_timeline).
    op.execute("""
        CREATE INDEX ix_guest_events_tenant_inquiry_time
        ON guest_events (tenant_id, inquiry_id, occurred_at DESC)
    """)

    op.execute("ALTER TABLE guest_events ENABLE ROW LEVEL SECURITY")
    # FORCE as well as ENABLE — without it the table owner bypasses the policy
    # entirely, and this table holds guest PII (message previews). Matches the
    # foundational RLS migration 002, which FORCEs every tenant-scoped table.
    op.execute("ALTER TABLE guest_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY guest_events_tenant_iso ON guest_events
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS guest_events_tenant_iso ON guest_events")
    op.execute("DROP INDEX IF EXISTS ix_guest_events_tenant_inquiry_time")
    op.execute("DROP INDEX IF EXISTS ix_guest_events_tenant_guest_time")
    op.drop_index("ix_guest_events_inquiry_id", table_name="guest_events")
    op.drop_index("ix_guest_events_guest_id", table_name="guest_events")
    op.drop_index("ix_guest_events_tenant_id", table_name="guest_events")
    op.drop_table("guest_events")
