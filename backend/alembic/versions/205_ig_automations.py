"""Instagram automations (comment/story/DM → DM): ig_automation_events + ig_tracked_links.

ig_automation_events: one row per step an automation took for a person (triggered, public_reply, dm_sent, dm_failed,
gate_asked, followed, link_sent, clicked, skipped) -- the stats per automation and the once-per-person check read it.
ig_tracked_links: the short codes behind a DM's button; GET /l/{code} logs a click and redirects to target_url.
tenant_id + forced RLS. Idempotent (IF NOT EXISTS, guarded policies) because production runs create_all at startup.

Revision ID: 205
Revises: 204
"""
from alembic import op

revision = "205"
down_revision = "204"
branch_labels = None
depends_on = None

_TABLES = ("ig_automation_events", "ig_tracked_links")


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ig_automation_events (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
            rule_id     VARCHAR(36) NOT NULL,
            guest_id    VARCHAR,
            media_id    VARCHAR(64),
            kind        VARCHAR(20) NOT NULL,
            detail      VARCHAR(300),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ig_automation_events_tenant_id ON ig_automation_events (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ig_automation_events_rule ON ig_automation_events (tenant_id, rule_id, kind)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ig_automation_events_guest ON ig_automation_events (tenant_id, guest_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS ig_tracked_links (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
            rule_id     VARCHAR(36) NOT NULL,
            code        VARCHAR(16) NOT NULL,
            target_url  TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ig_tracked_links_code UNIQUE (code)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ig_tracked_links_tenant_id ON ig_tracked_links (tenant_id)")
    for t in _TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{t}' AND policyname = '{t}_tenant_isolation') THEN
                    CREATE POLICY {t}_tenant_isolation ON {t}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t}")
