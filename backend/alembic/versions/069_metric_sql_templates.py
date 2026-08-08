"""Write real sql_templates for the metrics computable without the blocked
stay-date schema fix (HAIP_Dashboard_Metrics_Plan.md Phase 2, steps 2.3 + 2.5)

Renumbered from the plan's own "070" -- the plan assumed step 2.2 (stay
dates String->Date) would land first as "069", but that migration is
explicitly deferred pending the pre-flight row-count check against
production data the plan itself requires before running it (a bare cast
would fail on any non-ISO check_in/check_out value, and Ratha's stays were
hand-entered). Rather than reserve a gap and risk a chain edit later once
069 does land, this migration simply takes the next real revision number.
When the stay-date migration is written, it becomes 071 (revises 070) and
this file's down_revision does not need to change.

Scope discipline per the plan: only metrics whose backing tables and
timestamp columns are already safe to query. Explicitly NOT included here
(sql_template stays NULL, tiles stay hidden):
  - cm_revenue_mtd / cm_adr / cm_occupancy_pct -- blocked on the stay-date
    schema fix (F5); casting Stay.check_in/check_out blind is exactly what
    that migration exists to avoid doing unsafely.
  - ads_* (8 metrics) -- need Phase 3's ad_metrics table, which does not
    exist yet.
  - leads_funnel_valid -- a stage-by-stage breakdown, not a single scalar;
    doesn't fit metrics_registry's one-scalar-per-template model as-is.

Timestamp-column note: several tables (Call.started_at, Inquiry.
first_response_at) store timestamps as app-generated ISO8601 strings, not
native timestamptz -- always well-formed since the app writes them via
datetime.now(timezone.utc).isoformat(), unlike Stay's hand-entered dates.
Cast via NULLIF(col, '')::timestamptz -- the NULLIF guard exists because
an empty-but-present string reaching a raw Postgres timestamptz comparison
is a real, previously-hit bug (confirmed live, fixed in commit 6e0a34e for
Leads360's date filters -- same failure mode, defended against here too).

Revision ID: 069
Revises: 068
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


# ── New metric keys (plan step 2.5) ────────────────────────────────────────────
_NEW_METRICS = """
INSERT INTO metrics_registry
    (metric_key, metric_name, description, module_code, aggregation_type, unit,
     required_tables, compatible_widget_types, refresh_frequency, cache_ttl_seconds)
VALUES
  ('leads_valid_active',      'Active Valid Leads',        'Open inquiries in a valid-category pipeline stage', 'leads360', 'count', 'count',
   '["inquiries","pipeline_stages"]', '["kpi"]', 1800, 300),
  ('msg_first_response_avg',  'Avg First Response Time',   'Mean seconds from inquiry created to first response', 'whatsapp', 'avg', 'seconds',
   '["inquiries"]', '["kpi","line"]', 3600, 900),
  ('msg_sla_breach_count',    'SLA Breaches',              'Inquiries that breached first-response SLA', 'whatsapp', 'count', 'count',
   '["inquiries"]', '["kpi","bar"]', 3600, 900),
  ('ai_draft_verbatim_rate',  'AI Draft Verbatim Rate',    'AI drafts sent unedited / total outcomes', 'ai_concierge', 'ratio', '%',
   '["ai_draft_outcomes"]', '["kpi","progress"]', 3600, 900),
  ('ai_draft_edit_distance_avg', 'AI Draft Avg Edit Distance', 'Mean edit distance %% for sent-edited drafts', 'ai_concierge', 'avg', '%',
   '["ai_draft_outcomes"]', '["kpi"]', 3600, 900),
  ('ai_draft_reject_rate',    'AI Draft Reject Rate',      'AI drafts rejected / total outcomes', 'ai_concierge', 'ratio', '%',
   '["ai_draft_outcomes"]', '["kpi"]', 3600, 900),
  ('ai_fact_accuracy',        'AI Fact Accuracy',          'Grounded facts verified correct / total verdicts', 'ai_concierge', 'ratio', '%',
   '["ai_draft_outcomes"]', '["kpi"]', 3600, 900)
"""

_TEMPLATES = {
    # ── Calls (tile 7) -- Mcube exclusion per migration 064 ─────────────────
    "calls_volume": """
        SELECT COUNT(*) FROM calls
        WHERE tenant_id = :tenant_id
          AND NULLIF(started_at, '')::timestamptz >= :start_date
          AND NULLIF(started_at, '')::timestamptz < :end_date
          AND (
            (SELECT ivr_provider FROM tenants WHERE id = :tenant_id) IS NULL
            OR ivr_provider = (SELECT ivr_provider FROM tenants WHERE id = :tenant_id)
          )
    """,
    "calls_missed": """
        SELECT COUNT(*) FROM calls
        WHERE tenant_id = :tenant_id
          AND direction = 'inbound'
          AND COALESCE(duration_seconds, 0) = 0
          AND NULLIF(started_at, '')::timestamptz >= :start_date
          AND NULLIF(started_at, '')::timestamptz < :end_date
          AND (
            (SELECT ivr_provider FROM tenants WHERE id = :tenant_id) IS NULL
            OR ivr_provider = (SELECT ivr_provider FROM tenants WHERE id = :tenant_id)
          )
    """,
    "calls_qa_avg": """
        SELECT AVG(ai_score) FROM calls
        WHERE tenant_id = :tenant_id
          AND ai_score IS NOT NULL
          AND NULLIF(started_at, '')::timestamptz >= :start_date
          AND NULLIF(started_at, '')::timestamptz < :end_date
          AND (
            (SELECT ivr_provider FROM tenants WHERE id = :tenant_id) IS NULL
            OR ivr_provider = (SELECT ivr_provider FROM tenants WHERE id = :tenant_id)
          )
    """,
    # ── Leads (tile 5) -- category='valid' per pipeline_stages, not the
    # legacy Inquiry.stage enum (CLAUDE.md: only 'valid' stages count) ──────
    "leads_valid_active": """
        SELECT COUNT(*) FROM inquiries i
        JOIN pipeline_stages ps ON ps.id = i.stage_id
        WHERE i.tenant_id = :tenant_id
          AND ps.category = 'valid'
          AND ps.is_closed_won = false
          AND ps.is_closed_lost = false
    """,
    # ── Response speed (tile 6) ──────────────────────────────────────────────
    "msg_first_response_avg": """
        SELECT AVG(EXTRACT(EPOCH FROM (
            NULLIF(first_response_at, '')::timestamptz - created_at
        )))
        FROM inquiries
        WHERE tenant_id = :tenant_id
          AND first_response_at IS NOT NULL AND first_response_at != ''
          AND created_at >= :start_date AND created_at < :end_date
    """,
    "msg_sla_breach_count": """
        SELECT COUNT(*) FROM inquiries
        WHERE tenant_id = :tenant_id
          AND sla_breached = true
          AND created_at >= :start_date AND created_at < :end_date
    """,
    # ── AI trust scorecard (tile 8) -- from ai_draft_outcomes (migration
    # 058), already populated, surfaced nowhere until now ────────────────────
    "ai_draft_verbatim_rate": """
        SELECT
          CASE WHEN COUNT(*) = 0 THEN NULL
          ELSE 100.0 * COUNT(*) FILTER (WHERE outcome = 'sent_verbatim') / COUNT(*)
          END
        FROM ai_draft_outcomes
        WHERE tenant_id = :tenant_id
          AND created_at >= :start_date AND created_at < :end_date
    """,
    "ai_draft_edit_distance_avg": """
        SELECT AVG(edit_distance_pct)
        FROM ai_draft_outcomes
        WHERE tenant_id = :tenant_id
          AND outcome = 'sent_edited'
          AND created_at >= :start_date AND created_at < :end_date
    """,
    "ai_draft_reject_rate": """
        SELECT
          CASE WHEN COUNT(*) = 0 THEN NULL
          ELSE 100.0 * COUNT(*) FILTER (WHERE outcome = 'rejected') / COUNT(*)
          END
        FROM ai_draft_outcomes
        WHERE tenant_id = :tenant_id
          AND created_at >= :start_date AND created_at < :end_date
    """,
    "ai_fact_accuracy": """
        SELECT
          CASE WHEN COUNT(*) FILTER (WHERE fact_verdict IS NOT NULL) = 0 THEN NULL
          ELSE 100.0 * COUNT(*) FILTER (WHERE fact_verdict = 'correct')
               / COUNT(*) FILTER (WHERE fact_verdict IS NOT NULL)
          END
        FROM ai_draft_outcomes
        WHERE tenant_id = :tenant_id
          AND created_at >= :start_date AND created_at < :end_date
    """,
}


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(_NEW_METRICS))
    for metric_key, template in _TEMPLATES.items():
        bind.execute(
            sa.text("UPDATE metrics_registry SET sql_template = :tpl WHERE metric_key = :key"),
            {"tpl": template.strip(), "key": metric_key},
        )


def downgrade():
    bind = op.get_bind()
    for metric_key in _TEMPLATES:
        bind.execute(
            sa.text("UPDATE metrics_registry SET sql_template = NULL WHERE metric_key = :key"),
            {"key": metric_key},
        )
    bind.execute(sa.text(
        "DELETE FROM metrics_registry WHERE metric_key IN ("
        "'leads_valid_active','msg_first_response_avg','msg_sla_breach_count',"
        "'ai_draft_verbatim_rate','ai_draft_edit_distance_avg','ai_draft_reject_rate','ai_fact_accuracy'"
        ")"
    ))
