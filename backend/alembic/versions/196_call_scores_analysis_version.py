"""One AI call per phone call (8 Nov 2026): call_scores.analysis_version, so a call has ONE score row per prompt version.

The call pipeline (classify + judge + deep_reason re-judge + wrap-up) is one LLM call now (tasks.analyze_call,
prompt call-analysis-v6). Its retries and call_recovery's runs used to add a new call_scores row each time, and the QA
report lists every row. Now:
  * call_scores.analysis_version VARCHAR(40) NULL
  * unique index uq_call_scores_call_version ON call_scores (tenant_id, call_id, analysis_version)
    WHERE analysis_version IS NOT NULL
Older rows keep NULL (their duplicates stay as they are, the index ignores them). Existing tenant-scoped table: its RLS
policy is unchanged. ADD COLUMN / CREATE UNIQUE INDEX IF NOT EXISTS: idempotent, and repairs a table created by
create_all (prod runs create_all).

Revision ID: 196
Revises: 195
"""

from alembic import op

revision = "196"
down_revision = "195"
branch_labels = None
depends_on = None

INDEX = "uq_call_scores_call_version"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE call_scores ADD COLUMN IF NOT EXISTS analysis_version VARCHAR(40)")
    else:
        existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(call_scores)")}
        if "analysis_version" not in existing:
            op.execute("ALTER TABLE call_scores ADD COLUMN analysis_version VARCHAR(40)")
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON call_scores (tenant_id, call_id, analysis_version) "
        "WHERE analysis_version IS NOT NULL"
    )


def downgrade():
    bind = op.get_bind()
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE call_scores DROP COLUMN IF EXISTS analysis_version")
    else:
        op.drop_column("call_scores", "analysis_version")
