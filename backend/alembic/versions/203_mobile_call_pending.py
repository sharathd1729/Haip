"""HAIP Calls app, step 2 (docs/MOBILE_CALL_TRACKING_SPEC.md): mobile_call_pending.

A call a phone uploaded that call_ingest has not created yet, plus its recording when the file arrived before the call row.
call_ingest attaches the recording and deletes the row; stale rows are swept with their file. tenant_id + forced RLS.
No calls schema change: the recording lands in the existing calls.recording_s3_key / recording_status columns.
Idempotent (IF NOT EXISTS, guarded policy) because production runs create_all at startup.

Revision ID: 203
Revises: 202
"""
from alembic import op

revision = "203"
down_revision = "202"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS mobile_call_pending (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
            device_pk       VARCHAR NOT NULL REFERENCES mobile_devices(id),
            ivr_call_id     VARCHAR(255) NOT NULL,
            recording_key   TEXT,
            recording_type  VARCHAR(20),
            recording_bytes INTEGER,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_mobile_call_pending_tenant_call UNIQUE (tenant_id, ivr_call_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mobile_call_pending_tenant_id ON mobile_call_pending (tenant_id)")
    op.execute("ALTER TABLE mobile_call_pending ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mobile_call_pending FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'mobile_call_pending' AND policyname = 'mobile_call_pending_tenant_isolation'
            ) THEN
                CREATE POLICY mobile_call_pending_tenant_isolation ON mobile_call_pending
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS mobile_call_pending")
