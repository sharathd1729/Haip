"""Drop the tables behind removed features

Cleanup pass (Sept 2026), approved by the workspace owner. Every table here
belongs to a feature with no screen, no API route and no background job left
in the codebase after this commit:

  * Custom dashboards / widgets / metrics engine / goals -- a second
    dashboard system, switched off 2026-08-08, never rebuilt. Its beat
    schedules were already commented out.
  * The older owner-dashboard widget grid (dashboard_widgets), same date.
  * Property sharing -- model and service existed, nothing called them.
  * The multi-step Ask HAIP engine (sessions, findings, reports, alerts) and
    the two emails it fed. The free-form analyst -- the one the Claude
    connector uses -- stays, with its ask_haip_freeform_queries table.
  * inquiry_property_links -- written by nothing, read by nothing.
  * tenants.handoff_* -- the bot's call/WhatsApp handoff, reverted today.

Downgrade recreates the tables empty (shape only); the rows are not
recoverable, which is why this was confirmed before it was written.

Revision ID: 104
Revises: 103
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "104"
down_revision = "103"
branch_labels = None
depends_on = None

# Child tables first: dashboard_widget_instances and dashboard_shares point at
# dashboards, property_share_events at property_shares.
TABLES = [
    "dashboard_widget_instances",
    "dashboard_shares",
    "dashboards",
    "dashboard_templates",
    "dashboard_widgets",
    "widget_registry",
    "metric_snapshots",
    "metrics_registry",
    "goals",
    "property_share_events",
    "property_shares",
    "inquiry_property_links",
    "ask_haip_findings",
    "ask_haip_reports",
    "ask_haip_alerts",
    "ask_haip_sessions",
]

TENANT_COLUMNS = ["handoff_phone", "handoff_whatsapp_url", "handoff_enabled"]


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    for table in TABLES:
        if table in existing:
            op.drop_table(table)

    tenant_cols = {c["name"] for c in insp.get_columns("tenants")}
    for col in TENANT_COLUMNS:
        if col in tenant_cols:
            op.drop_column("tenants", col)


def downgrade():
    # Shape only -- the dropped rows are gone. Enough for a clean re-run of
    # later migrations, not a restore.
    op.add_column("tenants", sa.Column("handoff_phone", sa.String(20), nullable=True))
    op.add_column("tenants", sa.Column("handoff_whatsapp_url", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column("handoff_enabled", sa.Boolean(), nullable=False, server_default="true"))
    for table in ("ask_haip_sessions", "ask_haip_alerts", "ask_haip_reports", "ask_haip_findings",
                  "inquiry_property_links", "property_shares", "property_share_events", "goals",
                  "metrics_registry", "metric_snapshots", "widget_registry", "dashboard_widgets",
                  "dashboard_templates", "dashboards", "dashboard_shares", "dashboard_widget_instances"):
        op.create_table(
            table,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=True),
        )
