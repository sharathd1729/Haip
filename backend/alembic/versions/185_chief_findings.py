"""AI Executive E1 (3 Nov 2026): the Executive's findings live in the existing ``insights`` table (one store, one panel).

Adds columns to an existing tenant-scoped table (its RLS policy is unchanged; no new table):
  * insights.role VARCHAR(30)              -- the Executive role that owns the finding (schemas/chief.ROLE_LABELS)
  * insights.evidence JSON                 -- record ids only (inquiries, stays, feeds ...), never names or phone numbers
  * insights.numbers JSON                  -- the figures the AI explanation may quote (number grounding)
  * insights.explanation JSON              -- {why, next_step, source, numbers_sha, prompt_version, at}
  * insights.first_seen_at / last_seen_at TIMESTAMPTZ
  * insights.dismiss_reason VARCHAR(20)    -- not_now | wrong | already_handled | too_risky | not_worth_it
  * insights.snoozed_until TIMESTAMPTZ     -- a dismissed finding is not raised again before this
  * index ix_insights_tenant_id_role
183 and 184 are taken by the website branch (PR #112); re-parent this file on its head when both merge.
ADD COLUMN / CREATE INDEX IF NOT EXISTS: idempotent, and repairs a table created by create_all (prod runs create_all).

Revision ID: 185
Revises: 182
"""

from alembic import op

revision = "185"
down_revision = "182"
branch_labels = None
depends_on = None

COLUMNS = (
    ("role", "VARCHAR(30)"),
    ("evidence", "JSON"),
    ("numbers", "JSON"),
    ("explanation", "JSON"),
    ("first_seen_at", "TIMESTAMP WITH TIME ZONE"),
    ("last_seen_at", "TIMESTAMP WITH TIME ZONE"),
    ("dismiss_reason", "VARCHAR(20)"),
    ("snoozed_until", "TIMESTAMP WITH TIME ZONE"),
)
INDEX = "ix_insights_tenant_id_role"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        for name, kind in COLUMNS:
            op.execute(f"ALTER TABLE insights ADD COLUMN IF NOT EXISTS {name} {kind}")
    else:
        existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(insights)")}
        for name, kind in COLUMNS:
            if name not in existing:
                op.execute(f"ALTER TABLE insights ADD COLUMN {name} {kind}")
    op.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON insights (tenant_id, role)")


def downgrade():
    bind = op.get_bind()
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
    for name, _ in reversed(COLUMNS):
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE insights DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column("insights", name)
