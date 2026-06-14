"""Metric registry and widget registry with seed data

Revision ID: 032
Revises: 031
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade():
    # ── metrics_registry (global) ─────────────────────────────────────────────
    op.create_table(
        "metrics_registry",
        sa.Column("metric_key", sa.String(60), primary_key=True),
        sa.Column("metric_name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("module_code", sa.String(40), nullable=False),
        sa.Column("aggregation_type", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("sql_template", sa.Text(), nullable=True),
        sa.Column("required_tables", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("compatible_widget_types", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("refresh_frequency", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("cache_ttl_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_metrics_registry_module", "metrics_registry", ["module_code"])

    # ── widget_registry (global) ──────────────────────────────────────────────
    op.create_table(
        "widget_registry",
        sa.Column("widget_key", sa.String(60), primary_key=True),
        sa.Column("widget_name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("widget_type", sa.String(30), nullable=False),
        sa.Column("required_modules", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("required_metrics", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("required_feature_flags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("default_metric_bindings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("min_data_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refresh_hours", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="true"),
    )

    # ── seed: metrics ─────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO metrics_registry
            (metric_key, metric_name, description, module_code, aggregation_type, unit,
             required_tables, compatible_widget_types, refresh_frequency, cache_ttl_seconds)
        VALUES
          -- WhatsApp
          ('wa_conversations_count', 'Conversations', 'Total WA conversations', 'whatsapp', 'count', 'count',
           '["conversations"]', '["kpi","bar","line"]', 3600, 900),
          ('wa_response_time_p95',   'WA Response Time P95', 'p95 first reply latency on WA', 'whatsapp', 'p95', 'seconds',
           '["conversations","messages"]', '["kpi","line"]', 3600, 900),
          ('wa_ai_draft_rate',       'AI Draft Rate', 'AI-generated / total outbound msgs', 'whatsapp', 'ratio', '%',
           '["messages"]', '["kpi","progress"]', 3600, 900),
          ('wa_lead_conversion',     'WA Lead Conversion', 'WA inquiries that became bookings', 'whatsapp', 'ratio', '%',
           '["inquiries","conversations"]', '["kpi","bar"]', 7200, 1800),
          ('wa_template_delivery',   'Template Delivery Rate', 'Delivered / sent WA templates', 'whatsapp', 'ratio', '%',
           '["messages"]', '["kpi","bar"]', 3600, 900),

          -- Instagram
          ('ig_dm_count',            'Instagram DMs', 'Total Instagram DMs received', 'instagram', 'count', 'count',
           '["conversations","messages"]', '["kpi","bar","line"]', 3600, 900),
          ('ig_response_time_p95',   'IG Response Time P95', 'p95 first reply latency on IG', 'instagram', 'p95', 'seconds',
           '["conversations","messages"]', '["kpi","line"]', 3600, 900),
          ('ig_lead_count',          'IG Leads', 'Inquiries sourced from Instagram', 'instagram', 'count', 'count',
           '["inquiries"]', '["kpi","bar"]', 3600, 900),

          -- Channel Manager
          ('cm_bookings_count',      'Bookings', 'Confirmed bookings count', 'channel_manager', 'count', 'count',
           '["stays"]', '["kpi","bar","line"]', 3600, 900),
          ('cm_occupancy_pct',       'Occupancy %', 'Occupied nights / available nights × 100', 'channel_manager', 'ratio', '%',
           '["stays","properties"]', '["kpi","heatmap","line"]', 3600, 900),
          ('cm_revenue_mtd',         'Revenue MTD', 'Confirmed stay revenue month-to-date', 'channel_manager', 'sum', 'INR',
           '["stays"]', '["kpi","bar","line","goal"]', 900, 300),
          ('cm_adr',                 'ADR', 'Average Daily Rate', 'channel_manager', 'avg', 'INR',
           '["stays"]', '["kpi","line"]', 3600, 900),
          ('cm_revpar',              'RevPAR', 'Revenue per Available Room', 'channel_manager', 'ratio', 'INR',
           '["stays","properties"]', '["kpi","line"]', 3600, 900),
          ('cm_lost_revenue',        'Lost Revenue', 'Budget of lost/ghosted inquiries', 'channel_manager', 'sum', 'INR',
           '["inquiries"]', '["kpi","bar"]', 7200, 1800),
          ('cm_guest_ltv',           'Guest LTV', 'Lifetime revenue per unique guest', 'channel_manager', 'avg', 'INR',
           '["stays","guests"]', '["kpi","table"]', 86400, 21600),

          -- Calls
          ('calls_volume',           'Call Volume', 'Total calls in period', 'calls', 'count', 'count',
           '["calls"]', '["kpi","bar","line"]', 3600, 900),
          ('calls_avg_duration',     'Avg Call Duration', 'Average call length in seconds', 'calls', 'avg', 'seconds',
           '["calls"]', '["kpi","line"]', 3600, 900),
          ('calls_conversion_rate',  'Call Conversion', 'Calls that resulted in a booking', 'calls', 'ratio', '%',
           '["calls","inquiries"]', '["kpi","bar"]', 7200, 1800),
          ('calls_missed',           'Missed Calls', 'Calls with no-answer disposition', 'calls', 'count', 'count',
           '["calls"]', '["kpi","bar"]', 1800, 600),
          ('calls_qa_avg',           'Avg QA Score', 'Average AI quality score /10', 'calls', 'avg', '/10',
           '["calls"]', '["kpi","line","bar","goal"]', 3600, 900),
          ('calls_sentiment',        'Call Sentiment', 'Positive/neutral/negative split', 'calls', 'ratio', '%',
           '["calls"]', '["kpi","bar"]', 7200, 1800),

          -- Leads360
          ('leads_active',           'Active Inquiries', 'Inquiries in open pipeline stages', 'leads360', 'count', 'count',
           '["inquiries"]', '["kpi","funnel"]', 1800, 300),
          ('leads_funnel',           'Inquiry Funnel', 'Stage-by-stage inquiry counts', 'leads360', 'count', 'count',
           '["inquiries"]', '["funnel"]', 3600, 900),
          ('leads_response_p95',     'Response Time P95', 'p95 first response to inquiry', 'leads360', 'p95', 'seconds',
           '["inquiries"]', '["kpi","line"]', 3600, 900),
          ('leads_conversion_rate',  'Lead Conversion', 'Inquiries → bookings', 'leads360', 'ratio', '%',
           '["inquiries","stays"]', '["kpi","bar","goal"]', 7200, 1800),
          ('leads_sla_compliance',   'SLA Compliance', '(Responded − Breached) / Responded × 100', 'leads360', 'ratio', '%',
           '["inquiries"]', '["kpi","progress","goal"]', 3600, 900),
          ('leads_lost_reasons',     'Top Lost Reasons', 'Most common reasons inquiries are lost', 'leads360', 'count', 'count',
           '["inquiries"]', '["bar","table"]', 7200, 3600),

          -- AI Analytics
          ('ai_anomaly_score',       'Anomaly Score', 'Z-score annotated call volume anomalies', 'analytics', 'avg', 'z-score',
           '["calls"]', '["line"]', 3600, 900),
          ('ai_insights_count',      'Active AI Insights', 'Unread AI-generated insights', 'analytics', 'count', 'count',
           '["insights"]', '["kpi"]', 1800, 300),
          ('ai_churn_risk_pct',      'Churn Risk %', 'Guests predicted likely not to return', 'analytics', 'ratio', '%',
           '["stays","guests"]', '["kpi","table"]', 86400, 21600),
          ('ai_occupancy_forecast',  'Occupancy Forecast', '30-day forward occupancy projection', 'analytics', 'ratio', '%',
           '["stays","properties"]', '["line","kpi"]', 86400, 21600),
          ('ai_revenue_forecast',    'Revenue Forecast', '30-day projected revenue', 'analytics', 'sum', 'INR',
           '["stays","inquiries"]', '["line","kpi"]', 86400, 21600)
    """)

    # ── seed: widget registry (ports existing 18 + adds new) ─────────────────
    op.execute("""
        INSERT INTO widget_registry
            (widget_key, widget_name, description, category, widget_type,
             required_modules, required_metrics, min_data_rows, refresh_hours)
        VALUES
          -- Calls
          ('call_volume',         'Call Volume',         'Daily call count + QA trend',               'calls',     'bar',      '["calls"]',                         '["calls_volume","calls_qa_avg"]',    5,  4),
          ('call_sentiment',      'Call Sentiment',      'AI-scored call sentiment breakdown',         'calls',     'bar',      '["calls"]',                         '["calls_sentiment"]',                5,  4),
          ('missed_revenue',      'Missed Revenue',      'Lost-inquiry revenue at risk',               'calls',     'kpi',      '["calls","leads360"]',              '["cm_lost_revenue"]',                3,  6),
          ('top_objections',      'Top Objections',      'Recurring guest objection patterns',         'calls',     'bar',      '["calls","leads360"]',              '["leads_lost_reasons"]',             5,  6),
          ('intent_mix',          'Intent Mix',          'What guests are asking about',               'calls',     'bar',      '["calls"]',                         '["calls_volume"]',                   10, 6),
          ('agent_leaderboard',   'Agent Leaderboard',   'Concierge QA score ranking',                 'calls',     'table',    '["calls"]',                         '["calls_qa_avg"]',                   5,  4),

          -- Messaging
          ('response_time',       'Response Time',       'p95 first-reply latency',                   'messaging', 'kpi',      '[]',                                '["wa_response_time_p95"]',           5,  4),
          ('channel_mix',         'Channel Mix',         'Inbound volume by channel',                  'messaging', 'bar',      '["whatsapp"]',                      '["wa_conversations_count"]',         10, 4),
          ('campaign_performance','Campaign Performance','WhatsApp blast outcomes',                    'messaging', 'table',    '["campaigns"]',                     '[]',                                 5,  6),
          ('ai_draft_rate',       'AI Draft Rate',       'AI-generated message percentage',            'messaging', 'progress', '["ai_concierge","whatsapp"]',       '["wa_ai_draft_rate"]',               5,  4),

          -- Revenue
          ('inquiry_funnel',      'Inquiry Funnel',      'Stage-by-stage conversion',                  'revenue',   'funnel',   '["leads360"]',                      '["leads_funnel"]',                   10, 6),
          ('lead_attribution',    'Lead Attribution',    'Which sources drive bookings',               'revenue',   'bar',      '["leads360"]',                      '["leads_conversion_rate"]',          10, 24),
          ('occupancy_forecast',  'Occupancy Forecast',  '30-day forward occupancy',                  'revenue',   'line',     '["channel_manager","analytics"]',   '["ai_occupancy_forecast"]',          10, 24),
          ('revenue_forecast',    'Revenue Forecast',    '30-day projected revenue',                   'revenue',   'line',     '["channel_manager","analytics"]',   '["ai_revenue_forecast"]',            10, 24),
          ('pricing_signals',     'Pricing Signals',     'Rate vs. occupancy optimisation',            'revenue',   'table',    '["channel_manager","analytics"]',   '["cm_adr","cm_occupancy_pct"]',       10, 24),
          ('revenue_mtd',         'Revenue MTD',         'Month-to-date confirmed revenue',            'revenue',   'kpi',      '["channel_manager"]',               '["cm_revenue_mtd"]',                 1,  1),
          ('occupancy_heatmap',   'Occupancy Heatmap',   'Per-property occupancy grid',                'revenue',   'heatmap',  '["channel_manager"]',               '["cm_occupancy_pct"]',               1,  4),

          -- Guests
          ('guest_ltv',           'Guest LTV',           'Lifetime revenue per guest',                 'guests',    'kpi',      '["channel_manager"]',               '["cm_guest_ltv"]',                   20, 24),
          ('churn_risk',          'Churn Risk',          'Guests likely not to return',                'guests',    'table',    '["channel_manager","analytics"]',   '["ai_churn_risk_pct"]',              10, 24),
          ('guest_cohorts',       'Guest Cohorts',       'Repeat vs. new guest trends',                'guests',    'bar',      '["channel_manager"]',               '["cm_bookings_count"]',              20, 24),

          -- AI
          ('ai_recommendations',  'AI Recommendations',  'Prioritised action suggestions',             'ai',        'kpi',      '[]',                                '[]',                                 0,  6),
          ('ai_insights',         'AI Insights',         'Active AI-generated insights panel',         'ai',        'kpi',      '["analytics"]',                     '["ai_insights_count"]',              0,  2),

          -- Goals
          ('revenue_goal',        'Revenue Goal',        'Revenue vs. target',                         'revenue',   'goal',     '["channel_manager"]',               '["cm_revenue_mtd"]',                 1,  1),
          ('sla_goal',            'SLA Compliance Goal', 'SLA compliance vs. target',                  'operations','goal',     '["leads360"]',                      '["leads_sla_compliance"]',           1,  4),
          ('qa_goal',             'QA Score Goal',       'QA average vs. target',                      'calls',     'goal',     '["calls"]',                         '["calls_qa_avg"]',                   5,  4)
    """)


def downgrade():
    op.drop_index("ix_metrics_registry_module", table_name="metrics_registry")
    op.drop_table("widget_registry")
    op.drop_table("metrics_registry")
