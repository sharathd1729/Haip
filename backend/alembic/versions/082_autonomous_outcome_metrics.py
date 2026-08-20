"""Autonomous-send audit rows: persist intent, and keep human-review rates honest.

Two things:

1. `messages.ai_intent` -- the concierge classifies a per-message intent
   while drafting and then discards it. `ai_draft_outcomes.intent` has
   existed since migration 058 and no caller has ever populated it, so the
   per-intent accuracy that the autonomy graduation gate is supposed to be
   decided on could not be computed at all. Storing it on the message means
   the human approve/reject paths can record it too -- and those are the
   more important half, since deciding whether an intent is safe to run
   autonomously depends on how often humans sent that intent unedited.

2. Autonomous sends now write an ai_draft_outcomes row (outcome
   "sent_autonomous"). `ai_draft_verbatim_rate` and `ai_draft_reject_rate`
   divide by COUNT(*) over every outcome, so those new rows would land in
   the denominator while never matching the numerator -- quietly dragging
   both rates down and making the AI look worse the more it was trusted.
   Those two metrics measure *human review* behaviour, so autonomous rows
   are excluded from them here, and a separate metric reports the
   autonomous share instead.

Revision ID: 082
Revises: 081
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


_VERBATIM = """
SELECT
  CASE WHEN COUNT(*) = 0 THEN NULL
  ELSE 100.0 * COUNT(*) FILTER (WHERE outcome = 'sent_verbatim') / COUNT(*)
  END
FROM ai_draft_outcomes
WHERE tenant_id = :tenant_id
  AND outcome IN ('sent_verbatim', 'sent_edited', 'rejected')
  AND created_at >= :start_date AND created_at < :end_date
"""

_REJECT = """
SELECT
  CASE WHEN COUNT(*) = 0 THEN NULL
  ELSE 100.0 * COUNT(*) FILTER (WHERE outcome = 'rejected') / COUNT(*)
  END
FROM ai_draft_outcomes
WHERE tenant_id = :tenant_id
  AND outcome IN ('sent_verbatim', 'sent_edited', 'rejected')
  AND created_at >= :start_date AND created_at < :end_date
"""

_AUTONOMOUS_SHARE = """
SELECT
  CASE WHEN COUNT(*) = 0 THEN NULL
  ELSE 100.0 * COUNT(*) FILTER (WHERE outcome = 'sent_autonomous') / COUNT(*)
  END
FROM ai_draft_outcomes
WHERE tenant_id = :tenant_id
  AND created_at >= :start_date AND created_at < :end_date
"""

# Restores the pre-082 (unscoped) definitions on downgrade.
_VERBATIM_OLD = """
SELECT
  CASE WHEN COUNT(*) = 0 THEN NULL
  ELSE 100.0 * COUNT(*) FILTER (WHERE outcome = 'sent_verbatim') / COUNT(*)
  END
FROM ai_draft_outcomes
WHERE tenant_id = :tenant_id
  AND created_at >= :start_date AND created_at < :end_date
"""

_REJECT_OLD = """
SELECT
  CASE WHEN COUNT(*) = 0 THEN NULL
  ELSE 100.0 * COUNT(*) FILTER (WHERE outcome = 'rejected') / COUNT(*)
  END
FROM ai_draft_outcomes
WHERE tenant_id = :tenant_id
  AND created_at >= :start_date AND created_at < :end_date
"""


def upgrade():
    op.add_column("messages", sa.Column("ai_intent", sa.String(50), nullable=True))
    op.create_index("ix_ai_draft_outcomes_tenant_intent", "ai_draft_outcomes", ["tenant_id", "intent"])

    bind = op.get_bind()
    for key, tpl in (("ai_draft_verbatim_rate", _VERBATIM), ("ai_draft_reject_rate", _REJECT)):
        bind.execute(
            sa.text("UPDATE metrics_registry SET sql_template = :tpl WHERE metric_key = :key"),
            {"tpl": tpl.strip(), "key": key},
        )

    bind.execute(sa.text("""
        INSERT INTO metrics_registry
          (metric_key, metric_name, description, module_code, aggregation_type, unit,
           sql_template, required_tables, compatible_widget_types,
           refresh_frequency, cache_ttl_seconds, is_system)
        VALUES
          ('ai_autonomous_send_rate', 'AI Sent Without Review',
           'Share of AI drafts the AI sent by itself, with no human review.',
           'ai_concierge', 'ratio', '%',
           :tpl, '["ai_draft_outcomes"]', '["kpi"]', 3600, 900, true)
        ON CONFLICT (metric_key) DO UPDATE SET sql_template = EXCLUDED.sql_template
    """), {"tpl": _AUTONOMOUS_SHARE.strip()})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM metrics_registry WHERE metric_key = 'ai_autonomous_send_rate'"))
    for key, tpl in (("ai_draft_verbatim_rate", _VERBATIM_OLD), ("ai_draft_reject_rate", _REJECT_OLD)):
        bind.execute(
            sa.text("UPDATE metrics_registry SET sql_template = :tpl WHERE metric_key = :key"),
            {"tpl": tpl.strip(), "key": key},
        )
    op.drop_index("ix_ai_draft_outcomes_tenant_intent", table_name="ai_draft_outcomes")
    op.drop_column("messages", "ai_intent")
