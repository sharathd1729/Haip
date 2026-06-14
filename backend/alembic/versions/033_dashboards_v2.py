"""Dashboards v2: dashboards, dashboard_widget_instances, goals,
dashboard_templates, dashboard_shares, metric_snapshots

Revision ID: 033
Revises: 032
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


_RLS_TABLES = [
    "dashboards",
    "dashboard_widget_instances",
    "goals",
    "dashboard_shares",
    "metric_snapshots",
]

_POLICIES = {
    "dashboards":                  "dash_tenant_iso",
    "dashboard_widget_instances":  "dwi_tenant_iso",
    "goals":                       "goals_tenant_iso",
    "dashboard_shares":            "ds_tenant_iso",
    "metric_snapshots":            "ms_tenant_iso",
}


def upgrade():
    # ── dashboards ────────────────────────────────────────────────────────────
    op.create_table(
        "dashboards",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("layout_config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("date_range_default", sa.String(20), nullable=False, server_default="30d"),
        sa.Column("from_template_key", sa.String(60), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="private"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_dashboards_workspace_owner", "dashboards", ["workspace_id", "owner_id"])

    # ── dashboard_widget_instances ────────────────────────────────────────────
    op.create_table(
        "dashboard_widget_instances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("dashboard_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("widget_key", sa.String(60), nullable=False),
        sa.Column("title", sa.String(80), nullable=True),
        sa.Column("position", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("metric_bindings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("filters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("goal_id", sa.String(), nullable=True),
        sa.Column("display_config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("refresh_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("cached_data", postgresql.JSONB(), nullable=True),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_dwi_dashboard", "dashboard_widget_instances", ["dashboard_id"])
    op.create_index("ix_dwi_workspace", "dashboard_widget_instances", ["workspace_id"])

    # ── goals ─────────────────────────────────────────────────────────────────
    op.create_table(
        "goals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("metric_key", sa.String(60), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("target_value", sa.String(), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("property_ids", postgresql.JSONB(), nullable=True),
        sa.Column("alert_at_pct", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_goals_workspace", "goals", ["workspace_id"])

    # ── dashboard_templates ───────────────────────────────────────────────────
    op.create_table(
        "dashboard_templates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("template_key", sa.String(60), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("required_modules", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("layout_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("default_date_range", sa.String(20), nullable=False, server_default="30d"),
        sa.Column("target_roles", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("template_key", name="uq_dt_template_key"),
    )

    # ── dashboard_shares ──────────────────────────────────────────────────────
    op.create_table(
        "dashboard_shares",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("dashboard_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("principal_type", sa.String(20), nullable=False),
        sa.Column("principal_id", sa.String(), nullable=False),
        sa.Column("permission", sa.String(20), nullable=False),
        sa.Column("granted_by", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("dashboard_id", "principal_type", "principal_id",
                            name="uq_ds_dashboard_principal"),
    )
    op.create_index("ix_dashboard_shares_dashboard", "dashboard_shares", ["dashboard_id"])

    # ── metric_snapshots ──────────────────────────────────────────────────────
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("metric_key", sa.String(60), nullable=False),
        sa.Column("property_id", sa.String(), nullable=True),
        sa.Column("period_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granularity", sa.String(10), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "workspace_id", "metric_key", "property_id", "period_date", "granularity",
            name="uq_ms_workspace_metric_period",
        ),
    )
    op.create_index("ix_metric_snapshots_lookup", "metric_snapshots",
                    ["workspace_id", "metric_key", "period_date"])

    # ── RLS on all tenant-scoped tables ──────────────────────────────────────
    for table, policy in _POLICIES.items():
        col = "workspace_id"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {policy} ON {table}
            USING ({col} = current_setting('app.tenant_id', true)::text)
        """)

    # ── seed: system dashboard templates ──────────────────────────────────────
    op.execute("""
        INSERT INTO dashboard_templates
            (id, template_key, name, description, required_modules, layout_json,
             default_date_range, target_roles, is_system)
        VALUES
          (gen_random_uuid()::text, 'owner', 'Owner Dashboard',
           'High-level KPIs: revenue, occupancy, inquiries, QA',
           '["channel_manager","leads360"]',
           '{"widgets":[{"key":"revenue_mtd","pos":{"col":0,"row":0,"w":3,"h":2}},{"key":"cm_occupancy_pct","pos":{"col":3,"row":0,"w":3,"h":2}},{"key":"leads_active","pos":{"col":6,"row":0,"w":3,"h":2}},{"key":"calls_qa_avg","pos":{"col":9,"row":0,"w":3,"h":2}},{"key":"revenue_forecast","pos":{"col":0,"row":2,"w":8,"h":4}},{"key":"occupancy_heatmap","pos":{"col":8,"row":2,"w":4,"h":4}}]}',
           '30d', '["owner"]', true),

          (gen_random_uuid()::text, 'sales', 'Sales Dashboard',
           'Pipeline health: funnel, objections, SLA, response time',
           '["leads360"]',
           '{"widgets":[{"key":"inquiry_funnel","pos":{"col":0,"row":0,"w":6,"h":4}},{"key":"leads_conversion_rate","pos":{"col":6,"row":0,"w":3,"h":2}},{"key":"leads_response_p95","pos":{"col":9,"row":0,"w":3,"h":2}},{"key":"top_objections","pos":{"col":0,"row":4,"w":6,"h":4}},{"key":"sla_goal","pos":{"col":6,"row":4,"w":6,"h":4}}]}',
           '7d', '["owner","manager"]', true),

          (gen_random_uuid()::text, 'operations', 'Operations Dashboard',
           'Team performance: QA, SLA, agent leaderboard, AI draft rate',
           '["calls","leads360"]',
           '{"widgets":[{"key":"qa_goal","pos":{"col":0,"row":0,"w":4,"h":2}},{"key":"leads_sla_compliance","pos":{"col":4,"row":0,"w":4,"h":2}},{"key":"ai_draft_rate","pos":{"col":8,"row":0,"w":4,"h":2}},{"key":"agent_leaderboard","pos":{"col":0,"row":2,"w":6,"h":5}},{"key":"call_volume","pos":{"col":6,"row":2,"w":6,"h":5}}]}',
           '7d', '["owner","manager"]', true),

          (gen_random_uuid()::text, 'marketing', 'Marketing Dashboard',
           'Channel performance, AI draft rate, guest LTV, lead attribution',
           '["whatsapp","leads360"]',
           '{"widgets":[{"key":"channel_mix","pos":{"col":0,"row":0,"w":6,"h":4}},{"key":"ai_draft_rate","pos":{"col":6,"row":0,"w":3,"h":2}},{"key":"guest_ltv","pos":{"col":9,"row":0,"w":3,"h":2}},{"key":"lead_attribution","pos":{"col":0,"row":4,"w":8,"h":4}},{"key":"campaign_performance","pos":{"col":8,"row":4,"w":4,"h":4}}]}',
           '30d', '["owner","manager"]', true),

          (gen_random_uuid()::text, 'guest360', 'Guest 360 Dashboard',
           'Guest lifetime value, churn risk, cohort analysis',
           '["channel_manager","analytics"]',
           '{"widgets":[{"key":"guest_ltv","pos":{"col":0,"row":0,"w":4,"h":2}},{"key":"churn_risk","pos":{"col":4,"row":0,"w":4,"h":2}},{"key":"guest_cohorts","pos":{"col":8,"row":0,"w":4,"h":2}},{"key":"occupancy_heatmap","pos":{"col":0,"row":2,"w":12,"h":4}}]}',
           '90d', '["owner","manager"]', true),

          (gen_random_uuid()::text, 'revenue', 'Revenue Dashboard',
           'ADR, RevPAR, occupancy forecast, revenue forecast, pricing signals',
           '["channel_manager"]',
           '{"widgets":[{"key":"revenue_goal","pos":{"col":0,"row":0,"w":6,"h":2}},{"key":"cm_occupancy_pct","pos":{"col":6,"row":0,"w":3,"h":2}},{"key":"cm_revpar","pos":{"col":9,"row":0,"w":3,"h":2}},{"key":"revenue_forecast","pos":{"col":0,"row":2,"w":6,"h":4}},{"key":"occupancy_forecast","pos":{"col":6,"row":2,"w":6,"h":4}},{"key":"pricing_signals","pos":{"col":0,"row":6,"w":12,"h":4}}]}',
           '30d', '["owner"]', true)
    """)


def downgrade():
    for table, policy in _POLICIES.items():
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")

    op.drop_index("ix_metric_snapshots_lookup", table_name="metric_snapshots")
    op.drop_index("ix_dashboard_shares_dashboard", table_name="dashboard_shares")
    op.drop_index("ix_goals_workspace", table_name="goals")
    op.drop_index("ix_dwi_workspace", table_name="dashboard_widget_instances")
    op.drop_index("ix_dwi_dashboard", table_name="dashboard_widget_instances")
    op.drop_index("ix_dashboards_workspace_owner", table_name="dashboards")

    op.drop_table("metric_snapshots")
    op.drop_table("dashboard_shares")
    op.drop_table("dashboard_templates")
    op.drop_table("goals")
    op.drop_table("dashboard_widget_instances")
    op.drop_table("dashboards")
