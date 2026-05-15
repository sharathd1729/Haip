"""Add transcripts, integrations, consents, audit_events + RLS on all tenant tables

Revision ID: 002
Revises: 001
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

# Tables that need RLS (tenant-scoped)
TENANT_TABLES = [
    "guests", "inquiries", "conversations", "messages",
    "calls", "call_scores", "rubrics", "stays",
    "rate_plans", "properties",
]


def upgrade() -> None:
    # ── transcripts ───────────────────────────────────────────────────────────
    op.create_table(
        "transcripts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("call_id", sa.String, sa.ForeignKey("calls.id"), nullable=False, unique=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("language", sa.String(20)),
        sa.Column("redacted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("turns", sa.Text),          # JSON array of turn objects
        sa.Column("raw_text", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_transcripts_tenant_id", "transcripts", ["tenant_id"])
    op.create_index("ix_transcripts_call_id", "transcripts", ["call_id"])
    # pgvector column added via raw SQL (alembic type system doesn't cover it directly)
    op.execute("ALTER TABLE transcripts ADD COLUMN embedding vector(1024)")

    # ── integrations ──────────────────────────────────────────────────────────
    op.create_table(
        "integrations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("credentials_kms_blob", sa.LargeBinary),
        sa.Column("config", postgresql.JSONB, server_default="{}"),
        sa.Column("installed_at", sa.String),
        sa.Column("last_health_at", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_integrations_tenant_id", "integrations", ["tenant_id"])
    op.create_unique_constraint("uq_integrations_tenant_kind", "integrations", ["tenant_id", "kind"])

    # ── consents ──────────────────────────────────────────────────────────────
    op.create_table(
        "consents",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("guest_id", sa.String, sa.ForeignKey("guests.id"), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("scope", sa.String(50), nullable=False),
        sa.Column("granted", sa.Boolean, nullable=False),
        sa.Column("source", sa.String(50)),
        sa.Column("recorded_at", sa.String, nullable=False),
        sa.Column("expires_at", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_consents_tenant_id", "consents", ["tenant_id"])
    op.create_index("ix_consents_guest_id", "consents", ["guest_id"])

    # ── audit_events ──────────────────────────────────────────────────────────
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("actor_user_id", sa.String, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50)),
        sa.Column("target_id", sa.String),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("prev_hash", sa.Text),
        sa.Column("hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])

    # ── RLS on all tenant-scoped tables ───────────────────────────────────────
    # The app sets: SET app.tenant_id = '<uuid>' on every request via tenancy middleware
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::text)
        """)

    # Transcripts, integrations, consents get RLS too
    for table in ("transcripts", "integrations", "consents"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::text)
        """)

    # Audit events: read-only RLS for compliance role (insert bypasses via superuser worker)
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY audit_events_tenant_isolation ON audit_events
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade() -> None:
    for table in TENANT_TABLES + ["transcripts", "integrations", "consents"]:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS audit_events_tenant_isolation ON audit_events")
    op.drop_table("audit_events")
    op.drop_table("consents")
    op.drop_table("integrations")
    op.drop_table("transcripts")
