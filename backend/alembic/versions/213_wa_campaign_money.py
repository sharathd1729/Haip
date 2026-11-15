"""WhatsApp campaigns that show money (WhatsApp step 2).

- wa_pricing_events: Meta's per-message pricing from status webhooks (category, billable), one row per wamid, so
  cost per campaign / per lead / per booking can be worked out. tenant_id + forced RLS.
- wa_campaign_recipients.click_code / clicked_at: each recipient's tracked-link code (GET /api/v1/c/{code}).
- wa_campaigns.link_url (where the tracked button leads) and paused_reason (why it stopped: paused by a person,
  daily messaging limit, repeated failures).
Idempotent (IF NOT EXISTS, guarded policy) because production runs create_all at startup.

Revision ID: 213
Revises: 212
"""
from alembic import op

revision = "213"
down_revision = "212"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_pricing_events (
            id            VARCHAR PRIMARY KEY,
            tenant_id     VARCHAR NOT NULL REFERENCES tenants(id),
            wamid         VARCHAR(255) NOT NULL,
            category      VARCHAR(40),
            billable      BOOLEAN NOT NULL DEFAULT TRUE,
            pricing_model VARCHAR(20),
            occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_wa_pricing_events_wamid UNIQUE (tenant_id, wamid)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_wa_pricing_events_tenant_id ON wa_pricing_events (tenant_id, occurred_at)")
    op.execute("ALTER TABLE wa_pricing_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE wa_pricing_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'wa_pricing_events'
                           AND policyname = 'wa_pricing_events_tenant_isolation') THEN
                CREATE POLICY wa_pricing_events_tenant_isolation ON wa_pricing_events
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE wa_campaign_recipients ADD COLUMN IF NOT EXISTS click_code VARCHAR(16)")
    op.execute("ALTER TABLE wa_campaign_recipients ADD COLUMN IF NOT EXISTS clicked_at TIMESTAMPTZ")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_wa_campaign_recipients_click_code ON wa_campaign_recipients (click_code)")
    op.execute("ALTER TABLE wa_campaigns ADD COLUMN IF NOT EXISTS link_url TEXT")
    op.execute("ALTER TABLE wa_campaigns ADD COLUMN IF NOT EXISTS paused_reason VARCHAR(200)")


def downgrade():
    op.execute("ALTER TABLE wa_campaigns DROP COLUMN IF EXISTS paused_reason")
    op.execute("ALTER TABLE wa_campaigns DROP COLUMN IF EXISTS link_url")
    op.execute("DROP INDEX IF EXISTS uq_wa_campaign_recipients_click_code")
    op.execute("ALTER TABLE wa_campaign_recipients DROP COLUMN IF EXISTS clicked_at")
    op.execute("ALTER TABLE wa_campaign_recipients DROP COLUMN IF EXISTS click_code")
    op.execute("DROP TABLE IF EXISTS wa_pricing_events")
