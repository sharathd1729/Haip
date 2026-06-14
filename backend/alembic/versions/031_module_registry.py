"""Module registry, workspace_modules, feature_flags

Revision ID: 031
Revises: 030
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade():
    # ── modules (global, no RLS) ──────────────────────────────────────────────
    op.create_table(
        "modules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("requires_modules", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("provision_hook", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code", name="uq_modules_code"),
    )
    op.create_index("ix_modules_code", "modules", ["code"])

    # ── workspace_modules (tenant-scoped) ─────────────────────────────────────
    op.create_table(
        "workspace_modules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("module_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("workspace_id", "module_id", name="uq_wm_workspace_module"),
    )
    op.create_index("ix_workspace_modules_workspace_enabled", "workspace_modules",
                    ["workspace_id", "enabled"])

    op.execute("ALTER TABLE workspace_modules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY wm_tenant_iso ON workspace_modules
        USING (workspace_id = current_setting('app.tenant_id', true)::text)
    """)

    # ── feature_flags (workspace-scoped or global) ────────────────────────────
    op.create_table(
        "feature_flags",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("flag_key", sa.String(60), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.Column("value", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source", sa.String(20), nullable=False, server_default="default"),
        sa.Column("derived_from_module", sa.String(40), nullable=True),
        sa.Column("set_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("flag_key", "workspace_id", name="uq_ff_key_workspace"),
    )
    op.create_index("ix_feature_flags_workspace", "feature_flags", ["workspace_id"])

    # ── seed: module catalog ──────────────────────────────────────────────────
    op.execute("""
        INSERT INTO modules (id, code, name, description, category, status, requires_modules)
        VALUES
          (gen_random_uuid()::text, 'whatsapp',       'WhatsApp',         'WhatsApp Business API messaging',           'messaging', 'active', '[]'),
          (gen_random_uuid()::text, 'instagram',      'Instagram DM',     'Instagram Direct Messages',                 'messaging', 'active', '[]'),
          (gen_random_uuid()::text, 'calls',          'Calls / IVR',      'Voice calls, transcription, QA scoring',    'calls',     'active', '[]'),
          (gen_random_uuid()::text, 'leads360',       'Leads 360',        'Unified sales pipeline CRM',                'crm',       'active', '[]'),
          (gen_random_uuid()::text, 'channel_manager','Channel Manager',  'PMS sync, bookings, revenue, occupancy',    'revenue',   'active', '[]'),
          (gen_random_uuid()::text, 'analytics',      'AI Analytics',     'Advanced analytics, forecasting, insights', 'ai',        'active', '[]'),
          (gen_random_uuid()::text, 'ask_haip',       'Ask HAIP',         'AI-powered natural language analytics',     'ai',        'active', '["analytics"]'),
          (gen_random_uuid()::text, 'ai_concierge',   'AI Concierge',     'Shadow and autonomous WhatsApp replies',    'ai',        'active', '["whatsapp"]'),
          (gen_random_uuid()::text, 'campaigns',      'Campaigns',        'WhatsApp broadcast campaigns',              'messaging', 'active', '["whatsapp"]'),
          (gen_random_uuid()::text, 'flow_builder',   'Flow Builder',     'Automation flow builder',                   'automation','beta',   '[]')
    """)

    # ── seed: global feature flag defaults ────────────────────────────────────
    op.execute("""
        INSERT INTO feature_flags (id, flag_key, workspace_id, value, source)
        VALUES
          (gen_random_uuid()::text, 'whatsapp_enabled',              NULL, false, 'default'),
          (gen_random_uuid()::text, 'instagram_enabled',             NULL, false, 'default'),
          (gen_random_uuid()::text, 'calls_enabled',                 NULL, false, 'default'),
          (gen_random_uuid()::text, 'call_transcription_enabled',    NULL, false, 'default'),
          (gen_random_uuid()::text, 'call_qa_enabled',               NULL, false, 'default'),
          (gen_random_uuid()::text, 'leads360_enabled',              NULL, false, 'default'),
          (gen_random_uuid()::text, 'channel_manager_enabled',       NULL, false, 'default'),
          (gen_random_uuid()::text, 'revenue_reporting_enabled',     NULL, false, 'default'),
          (gen_random_uuid()::text, 'analytics_enabled',             NULL, false, 'default'),
          (gen_random_uuid()::text, 'ai_analytics_enabled',          NULL, false, 'default'),
          (gen_random_uuid()::text, 'forecasting_enabled',           NULL, false, 'default'),
          (gen_random_uuid()::text, 'anomaly_detection_enabled',     NULL, false, 'default'),
          (gen_random_uuid()::text, 'ask_haip_enabled',              NULL, false, 'default'),
          (gen_random_uuid()::text, 'ai_insights_enabled',           NULL, false, 'default'),
          (gen_random_uuid()::text, 'ai_drafts_enabled',             NULL, false, 'default'),
          (gen_random_uuid()::text, 'ai_concierge_enabled',          NULL, false, 'default'),
          (gen_random_uuid()::text, 'campaign_builder_enabled',      NULL, false, 'default'),
          (gen_random_uuid()::text, 'flow_builder_enabled',          NULL, false, 'default'),
          (gen_random_uuid()::text, 'churn_risk_enabled',            NULL, false, 'default'),
          (gen_random_uuid()::text, 'cohort_analysis_enabled',       NULL, false, 'default'),
          (gen_random_uuid()::text, 'occupancy_forecast_enabled',    NULL, false, 'default'),
          (gen_random_uuid()::text, 'missed_call_alerts_enabled',    NULL, false, 'default'),
          (gen_random_uuid()::text, 'pipeline_view_enabled',         NULL, false, 'default'),
          (gen_random_uuid()::text, 'sla_alerts_enabled',            NULL, false, 'default')
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS wm_tenant_iso ON workspace_modules")
    op.drop_index("ix_feature_flags_workspace", table_name="feature_flags")
    op.drop_index("ix_workspace_modules_workspace_enabled", table_name="workspace_modules")
    op.drop_index("ix_modules_code", table_name="modules")
    op.drop_table("feature_flags")
    op.drop_table("workspace_modules")
    op.drop_table("modules")
