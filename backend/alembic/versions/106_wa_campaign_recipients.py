"""WhatsApp campaign recipients: per-guest delivery record

New table wa_campaign_recipients (one row per guest a campaign was sent to)
with tenant_id and row-level security, same policy shape as the other wa_*
tables (017).

Production builds tables with create_all at API startup, which does not add
RLS -- so this migration creates the table itself if it is missing and then
always enables RLS and the policy. Every statement is idempotent, so it is
safe whichever of the two gets there first.

Revision ID: 106
Revises: 105
Create Date: 2026-09-25
"""
from alembic import op

revision = "106"
down_revision = "105"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_campaign_recipients (
            id             VARCHAR PRIMARY KEY,
            tenant_id      VARCHAR NOT NULL,
            campaign_id    VARCHAR NOT NULL,
            subscriber_id  VARCHAR,
            guest_id       VARCHAR,
            phone          VARCHAR(30) NOT NULL,
            name           VARCHAR(255),
            status         VARCHAR(20) NOT NULL DEFAULT 'queued',
            wa_message_id  VARCHAR(255),
            error_code     VARCHAR(30),
            error_reason   VARCHAR(500),
            sent_at        TIMESTAMPTZ,
            delivered_at   TIMESTAMPTZ,
            read_at        TIMESTAMPTZ,
            failed_at      TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_wa_campaign_recipient_phone UNIQUE (campaign_id, phone)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_wa_campaign_recipients_tenant_id ON wa_campaign_recipients (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wa_campaign_recipients_campaign_id ON wa_campaign_recipients (campaign_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wa_campaign_recipients_wa_message_id ON wa_campaign_recipients (wa_message_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wa_campaign_recipients_guest_id ON wa_campaign_recipients (guest_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wa_campaign_recipients_campaign_status "
        "ON wa_campaign_recipients (campaign_id, status)"
    )

    op.execute("ALTER TABLE wa_campaign_recipients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE wa_campaign_recipients FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'wa_campaign_recipients' AND policyname = 'wa_campaign_recipients_tenant_isolation'
            ) THEN
                CREATE POLICY wa_campaign_recipients_tenant_isolation ON wa_campaign_recipients
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS wa_campaign_recipients")
