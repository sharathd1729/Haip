"""Lead autopilot + actionable call insights

* ``lead_autopilot_events``: every stage decision the lead autopilot made (applied or only suggested), with its rule,
  reason, confidence, evidence (message/call/booking ids + quotes) and status (suggested/applied/undone/superseded/blocked).
  tenant_id + row-level security.
* ``inquiries.autopilot_paused_at`` / ``autopilot_paused_by``: staff pinned the lead, so the autopilot leaves it alone.
* ``calls.ai_insights``: the actionable read of a call (wrap_up prompt v5).

No data changes: the per-tenant mode lives in ``tenants.brand_config.lead_autopilot`` and defaults to "suggest" (today's
behaviour: recommendations only), so nothing moves until the owner switches autopilot on. Production builds tables with
create_all at startup (no RLS), so every statement is guarded and re-runnable.

Revision ID: 144
Revises: 141
Create Date: 2026-10-18
"""
from alembic import op

revision = "144"
down_revision = "141"
branch_labels = None
depends_on = None

_TABLE = "lead_autopilot_events"


def upgrade():
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
            inquiry_id       VARCHAR NOT NULL REFERENCES inquiries(id),
            from_stage_id    VARCHAR REFERENCES pipeline_stages(id),
            to_stage_id      VARCHAR NOT NULL REFERENCES pipeline_stages(id),
            source           VARCHAR(10) NOT NULL,
            rule             VARCHAR(40) NOT NULL,
            lost_reason      VARCHAR(30),
            reason           TEXT NOT NULL,
            confidence       NUMERIC(3, 2),
            evidence         JSON NOT NULL DEFAULT '[]',
            status           VARCHAR(12) NOT NULL DEFAULT 'suggested',
            mode             VARCHAR(10) NOT NULL,
            blocked_reason   TEXT,
            prompt_version   VARCHAR(60),
            model            VARCHAR(120),
            prev_lost_reason VARCHAR(30),
            prev_lost_note   TEXT,
            resolved_at      TIMESTAMPTZ,
            resolved_by      VARCHAR,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant_id ON {_TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant_inquiry ON {_TABLE} (tenant_id, inquiry_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant_status ON {_TABLE} (tenant_id, status)")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE tablename = '{_TABLE}' AND policyname = '{_TABLE}_tenant_isolation'
            ) THEN
                CREATE POLICY {_TABLE}_tenant_isolation ON {_TABLE}
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS autopilot_paused_at TIMESTAMPTZ")
    op.execute("ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS autopilot_paused_by VARCHAR")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS ai_insights JSON")


def downgrade():
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS ai_insights")
    op.execute("ALTER TABLE inquiries DROP COLUMN IF EXISTS autopilot_paused_by")
    op.execute("ALTER TABLE inquiries DROP COLUMN IF EXISTS autopilot_paused_at")
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
