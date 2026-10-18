"""HAIP's own website leads (platform_leads)

``platform_leads`` stores every book-demo / contact / property-assessment submission from HAIP's public website.
DOCUMENTED PLATFORM-LEVEL EXCEPTION: the rows belong to HAIP the company, are written by anonymous visitors before any
tenant is known, and are read only by the owner of HAIP's own sales workspace. No ``tenant_id`` column, so no tenant
policy (the RLS guard in tests/test_rls_postgres.py only covers tables that have one). The Leads360 copy of each lead
(guest, consent, inquiry) lives in normal tenant tables under their own RLS.

Production builds tables with create_all at startup, so every statement is guarded (IF NOT EXISTS). 142-144 belong to
branches not merged yet; whichever merges second needs a merge revision (like 127).

Revision ID: 145
Revises: 141
Create Date: 2026-10-18
"""
from alembic import op

revision = "145"
down_revision = "141"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform_leads (
            id                       VARCHAR PRIMARY KEY,
            kind                     VARCHAR(20) NOT NULL,
            submission_id            VARCHAR(64) NOT NULL,
            name                     VARCHAR(120) NOT NULL,
            email                    VARCHAR(255),
            phone                    VARCHAR(20),
            company                  VARCHAR(160),
            message                  TEXT,
            details                  JSON NOT NULL DEFAULT '{}',
            assessment               JSON,
            consent_given            BOOLEAN NOT NULL DEFAULT FALSE,
            marketing_opt_in         BOOLEAN NOT NULL DEFAULT FALSE,
            notice_version           VARCHAR(20),
            notice_text_hash         VARCHAR(64),
            consent_at               TIMESTAMPTZ,
            ip_hash                  VARCHAR(64),
            user_agent               VARCHAR(255),
            is_spam                  BOOLEAN NOT NULL DEFAULT FALSE,
            routing_status           VARCHAR(20) NOT NULL DEFAULT 'stored',
            routing_error            VARCHAR(300),
            workspace_tenant_id      VARCHAR,
            workspace_guest_id       VARCHAR,
            workspace_inquiry_id     VARCHAR,
            notified_at              TIMESTAMPTZ,
            narrative                TEXT,
            narrative_status         VARCHAR(12),
            narrative_prompt_version VARCHAR(40),
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_platform_leads_submission_id UNIQUE (submission_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_leads_ip_created ON platform_leads (ip_hash, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_leads_created ON platform_leads (created_at)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS platform_leads")
