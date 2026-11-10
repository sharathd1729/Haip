"""Meta lead-form leads: meta_form_leads (one row per imported form submission).

Revision ID: 200
Revises: 199

Idempotent (prod runs create_all at startup): CREATE ... IF NOT EXISTS and a guarded RLS policy.
"""

from alembic import op

revision = "200"
down_revision = "199"
branch_labels = None
depends_on = None

TABLE = "meta_form_leads"


def upgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    ts = "TIMESTAMPTZ NOT NULL DEFAULT now()" if postgres else "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
            leadgen_id      VARCHAR(64) NOT NULL,
            form_id         VARCHAR(64),
            form_name       VARCHAR(255),
            page_id         VARCHAR(64),
            ad_id           VARCHAR(64),
            adset_id        VARCHAR(64),
            campaign_id     VARCHAR(64),
            platform        VARCHAR(20),
            lead_created_at {"TIMESTAMPTZ" if postgres else "TIMESTAMP"},
            guest_id        VARCHAR REFERENCES guests(id),
            inquiry_id      VARCHAR REFERENCES inquiries(id),
            status          VARCHAR(20) NOT NULL DEFAULT 'created',
            created_at      {ts},
            updated_at      {ts}
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_guest_id ON {TABLE} (guest_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_inquiry_id ON {TABLE} (inquiry_id)")
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{TABLE}_tenant_leadgen ON {TABLE} (tenant_id, leadgen_id)")
    if postgres:
        op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{TABLE}' AND policyname = '{TABLE}_tenant_isolation') THEN
                    CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$;
        """)


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
