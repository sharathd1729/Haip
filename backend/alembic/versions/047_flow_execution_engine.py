"""WhatsApp module Phase 2: flow_pending_executions + wa_flow_runs

Revision ID: 047
Revises: 046
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _policy_exists(policy: str, table: str) -> bool:
    row = op.get_bind().execute(sa.text(
        "SELECT 1 FROM pg_policies WHERE policyname = :p AND tablename = :t"
    ), {"p": policy, "t": table}).first()
    return row is not None


def upgrade():
    if not _table_exists("flow_pending_executions"):
        op.create_table(
            "flow_pending_executions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("flow_id", sa.String(), nullable=False),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("guest_id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=True),
            sa.Column("context", sa.JSON(), server_default="{}"),
            sa.Column("resume_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_flow_pending_executions_tenant", "flow_pending_executions", ["tenant_id"])
        op.create_index("ix_flow_pending_executions_flow", "flow_pending_executions", ["flow_id"])
        op.create_index("ix_flow_pending_status_resume", "flow_pending_executions", ["status", "resume_at"])

    op.execute("ALTER TABLE flow_pending_executions ENABLE ROW LEVEL SECURITY")
    if not _policy_exists("flow_pending_executions_tenant_iso", "flow_pending_executions"):
        op.execute("""
            CREATE POLICY flow_pending_executions_tenant_iso ON flow_pending_executions
            USING (tenant_id = current_setting('app.tenant_id', true)::text)
        """)

    if not _table_exists("wa_flow_runs"):
        op.create_table(
            "wa_flow_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("flow_id", sa.String(), nullable=False),
            sa.Column("guest_id", sa.String(), nullable=False),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("node_type", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("detail", sa.String(500), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_wa_flow_runs_tenant", "wa_flow_runs", ["tenant_id"])
        op.create_index("ix_wa_flow_runs_flow", "wa_flow_runs", ["flow_id"])

    op.execute("ALTER TABLE wa_flow_runs ENABLE ROW LEVEL SECURITY")
    if not _policy_exists("wa_flow_runs_tenant_iso", "wa_flow_runs"):
        op.execute("""
            CREATE POLICY wa_flow_runs_tenant_iso ON wa_flow_runs
            USING (tenant_id = current_setting('app.tenant_id', true)::text)
        """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS wa_flow_runs_tenant_iso ON wa_flow_runs")
    op.drop_table("wa_flow_runs")
    op.execute("DROP POLICY IF EXISTS flow_pending_executions_tenant_iso ON flow_pending_executions")
    op.drop_table("flow_pending_executions")
