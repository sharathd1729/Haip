"""Lead workflows, phase 1: lead journey tracking + playbook runs

* ``lead_journeys``: one row per enquiry, the first time each milestone happened (received, assigned, notified, viewed,
  called, connected, contacted, proposal shared/delivered/read) and the outcome.
* ``lead_views``: who opened a lead and when.
* ``playbook_runs`` / ``playbook_actions``: what the lead playbooks (missed-call WhatsApp, unanswered-call WhatsApp, ...)
  did or skipped, and why. UNIQUE(tenant_id, playbook_key, trigger_ref) makes a repeated trigger a no-op.
* ``messages.sender_kind``: who/what wrote an outbound message, so automatic sends never count as a person's contact.
* ``inquiry_quotes.shared_message_id``: the WhatsApp message that carried a shared quote (delivered/read tracking).
* ``users.whatsapp_alerts_opt_in_at``: the person agreed to lead alerts on their own WhatsApp (used by phase 2).

Every table has tenant_id + row-level security. No data changes: every playbook is off until the owner switches it on in
Workflows (settings live in tenants.brand_config.lead_playbooks). Production builds tables with create_all at startup
(no RLS), so every statement is guarded and re-runnable.

Numbering: 147 and 149 are left for other open branches; this follows 150 (the head when it was written).

Revision ID: 151
Revises: 150
Create Date: 2026-10-20
"""
from alembic import op

revision = "151"
down_revision = "150"
branch_labels = None
depends_on = None

_TABLES = {
    "lead_journeys": """
        id                          VARCHAR PRIMARY KEY,
        tenant_id                   VARCHAR NOT NULL REFERENCES tenants(id),
        inquiry_id                  VARCHAR NOT NULL REFERENCES inquiries(id),
        guest_id                    VARCHAR REFERENCES guests(id),
        received_at                 TIMESTAMPTZ,
        received_via                VARCHAR(30),
        first_assigned_at           TIMESTAMPTZ,
        first_assigned_to           VARCHAR,
        first_notified_at           TIMESTAMPTZ,
        first_viewed_at             TIMESTAMPTZ,
        first_viewed_by             VARCHAR,
        first_call_attempt_at       TIMESTAMPTZ,
        first_connected_at          TIMESTAMPTZ,
        first_human_contact_at      TIMESTAMPTZ,
        first_human_contact_channel VARCHAR(20),
        proposal_shared_at          TIMESTAMPTZ,
        proposal_channel            VARCHAR(20),
        proposal_mode               VARCHAR(10),
        proposal_delivered_at       TIMESTAMPTZ,
        proposal_read_at            TIMESTAMPTZ,
        auto_messages               INTEGER NOT NULL DEFAULT 0,
        outcome                     VARCHAR(10) NOT NULL DEFAULT 'active',
        outcome_at                  TIMESTAMPTZ,
        lost_reason                 VARCHAR(30),
        playbooks_paused_at         TIMESTAMPTZ,
        playbooks_paused_by         VARCHAR,
        created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_lead_journeys_tenant_inquiry UNIQUE (tenant_id, inquiry_id)
    """,
    "lead_views": """
        id              VARCHAR PRIMARY KEY,
        tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
        inquiry_id      VARCHAR NOT NULL REFERENCES inquiries(id),
        user_id         VARCHAR NOT NULL REFERENCES users(id),
        first_viewed_at TIMESTAMPTZ NOT NULL,
        last_viewed_at  TIMESTAMPTZ NOT NULL,
        views           INTEGER NOT NULL DEFAULT 1,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_lead_views_tenant_inquiry_user UNIQUE (tenant_id, inquiry_id, user_id)
    """,
    "playbook_runs": """
        id           VARCHAR PRIMARY KEY,
        tenant_id    VARCHAR NOT NULL REFERENCES tenants(id),
        playbook_key VARCHAR(40) NOT NULL,
        trigger_ref  VARCHAR(120) NOT NULL,
        inquiry_id   VARCHAR REFERENCES inquiries(id),
        guest_id     VARCHAR REFERENCES guests(id),
        status       VARCHAR(12) NOT NULL DEFAULT 'scheduled',
        step         INTEGER NOT NULL DEFAULT 0,
        next_run_at  TIMESTAMPTZ,
        stop_reason  TEXT,
        context      JSON NOT NULL DEFAULT '{}',
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_playbook_runs_trigger UNIQUE (tenant_id, playbook_key, trigger_ref)
    """,
    "playbook_actions": """
        id                VARCHAR PRIMARY KEY,
        tenant_id         VARCHAR NOT NULL REFERENCES tenants(id),
        run_id            VARCHAR REFERENCES playbook_runs(id),
        playbook_key      VARCHAR(40) NOT NULL,
        inquiry_id        VARCHAR REFERENCES inquiries(id),
        guest_id          VARCHAR REFERENCES guests(id),
        action            VARCHAR(20) NOT NULL,
        status            VARCHAR(12) NOT NULL,
        reason            TEXT,
        message_id        VARCHAR,
        task_id           VARCHAR,
        recipient_user_id VARCHAR,
        template_name     VARCHAR(100),
        wa_message_id     VARCHAR(255),
        acked_at          TIMESTAMPTZ,
        payload           JSON NOT NULL DEFAULT '{}',
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
}

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_lead_journeys_tenant_received ON lead_journeys (tenant_id, received_at)",
    "CREATE INDEX IF NOT EXISTS ix_lead_journeys_tenant_outcome ON lead_journeys (tenant_id, outcome)",
    "CREATE INDEX IF NOT EXISTS ix_lead_journeys_guest_id ON lead_journeys (guest_id)",
    "CREATE INDEX IF NOT EXISTS ix_playbook_runs_status_next ON playbook_runs (status, next_run_at)",
    "CREATE INDEX IF NOT EXISTS ix_playbook_runs_tenant_inquiry ON playbook_runs (tenant_id, inquiry_id)",
    "CREATE INDEX IF NOT EXISTS ix_playbook_actions_tenant_guest ON playbook_actions (tenant_id, guest_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_playbook_actions_tenant_created ON playbook_actions (tenant_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_playbook_actions_tenant_inquiry ON playbook_actions (tenant_id, inquiry_id)",
    "CREATE INDEX IF NOT EXISTS ix_playbook_actions_wa_message_id ON playbook_actions (wa_message_id)",
]


def upgrade():
    for table, cols in _TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = '{table}' AND policyname = '{table}_tenant_isolation'
                ) THEN
                    CREATE POLICY {table}_tenant_isolation ON {table}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)
    for stmt in _INDEXES:
        op.execute(stmt)
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS sender_kind VARCHAR(20)")
    op.execute("ALTER TABLE inquiry_quotes ADD COLUMN IF NOT EXISTS shared_message_id VARCHAR")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_alerts_opt_in_at TIMESTAMPTZ")


def downgrade():
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS whatsapp_alerts_opt_in_at")
    op.execute("ALTER TABLE inquiry_quotes DROP COLUMN IF EXISTS shared_message_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS sender_kind")
    for table in ("playbook_actions", "playbook_runs", "lead_views", "lead_journeys"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
