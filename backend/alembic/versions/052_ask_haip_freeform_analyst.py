"""Ask HAIP free-form analyst: audit table + read-only DB role

Adds:
  - ask_haip_freeform_queries — audit trail for every NL->SQL attempt
    (accepted and rejected), with RLS like every other tenant table.
  - haip_analyst_ro — a dedicated Postgres role with SELECT-only grants on
    a fixed allowlist of analytics-safe tables. This is the actual security
    boundary for the free-form analyst: even if the SQL validator in
    ask_haip_freeform_service.py has a bug, this role physically cannot
    write, cannot see other tables (users, integrations, refresh_tokens,
    consents, etc.), and is subject to a short statement_timeout.

  SECURITY NOTE — deliberately does NOT set a login password here.
  Migration files are version-controlled; a hardcoded password would be a
  committed secret (CLAUDE.md: "No hardcoded secrets — environment
  variables only"). After this migration runs, an operator must run, once,
  directly against the production DB (not via this file, not committed
  anywhere):

      ALTER ROLE haip_analyst_ro WITH LOGIN PASSWORD '<generate a strong one>';

  ...and set ANALYST_RO_DATABASE_URL in the backend's .env to a connection
  string using that role/password. Until both of those are done, the
  free-form analyst service fails closed (raises on startup / first use)
  rather than falling back to a privileged connection.

Revision ID: 052
Revises: 051
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None

# Same tables the LLM's schema-context prompt is told about
# (ask_haip_freeform_service.py's ALLOWED_TABLES) -- kept in sync manually,
# the two lists must never diverge since this is what actually enforces
# access, not the prompt.
ANALYST_READABLE_TABLES = [
    "inquiries", "guests", "calls", "stays", "conversations", "messages",
    "properties", "pipeline_stages",
]


def _table_exists(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return insp.has_table(table)


def _role_exists(role: str) -> bool:
    bind = op.get_bind()
    return bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).first() is not None


def upgrade() -> None:
    if not _table_exists("ask_haip_freeform_queries"):
        op.create_table(
            "ask_haip_freeform_queries",
            sa.Column("id",            sa.String,  primary_key=True),
            sa.Column("tenant_id",     sa.String,  nullable=False, index=True),
            sa.Column("user_id",       sa.String,  nullable=True),
            sa.Column("question",      sa.Text,    nullable=False),
            sa.Column("generated_sql", sa.Text,    nullable=True),
            sa.Column("status",        sa.String(20), nullable=False),
            sa.Column("reject_reason", sa.Text,    nullable=True),
            sa.Column("row_count",     sa.Integer, nullable=True),
            sa.Column("duration_ms",   sa.Integer, nullable=True),
            sa.Column("chart_spec",    sa.JSON,    nullable=True),
            sa.Column("created_at",    sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at",    sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_ask_haip_freeform_queries_tenant", "ask_haip_freeform_queries", ["tenant_id"])
        op.create_index("ix_ask_haip_freeform_queries_status", "ask_haip_freeform_queries", ["status"])

        op.execute("ALTER TABLE ask_haip_freeform_queries ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE ask_haip_freeform_queries FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY ask_haip_freeform_queries_tenant_isolation ON ask_haip_freeform_queries
            USING (tenant_id = current_setting('app.tenant_id', true)::text)
        """)

    # ── Read-only analyst role ──────────────────────────────────────────────
    if not _role_exists("haip_analyst_ro"):
        # NOLOGIN until an operator sets a real password out-of-band (see
        # module docstring) -- a role with no login capability can't be used
        # to connect at all, so this is a safe default even before that step.
        op.execute("CREATE ROLE haip_analyst_ro NOLOGIN")

    op.execute("ALTER ROLE haip_analyst_ro SET statement_timeout = '5s'")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM haip_analyst_ro")
    for table in ANALYST_READABLE_TABLES:
        if _table_exists(table):
            op.execute(f"GRANT SELECT ON {table} TO haip_analyst_ro")


def downgrade() -> None:
    for table in ANALYST_READABLE_TABLES:
        if _table_exists(table):
            op.execute(f"REVOKE SELECT ON {table} FROM haip_analyst_ro")
    # Role itself intentionally left in place on downgrade -- dropping a role
    # that may have an operator-set password/active connections is not safe
    # to automate; drop manually if truly decommissioning this feature.

    op.execute("DROP POLICY IF EXISTS ask_haip_freeform_queries_tenant_isolation ON ask_haip_freeform_queries")
    op.execute("ALTER TABLE ask_haip_freeform_queries DISABLE ROW LEVEL SECURITY")
    op.drop_table("ask_haip_freeform_queries")
