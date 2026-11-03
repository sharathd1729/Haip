"""AI Executive E2 (3 Nov 2026): proposals (a finding + a plan of typed steps that an owner approves before anything runs).

New table only; nothing existing is altered. tenant_id NOT NULL and, on PostgreSQL, forced row-level security:
  * chief_proposals            one per finding while open (partial unique index), status, steps + results, plan_sha
                               (the approval is bound to it), decision (who, when, via app|whatsapp, reject reason),
                               baseline numbers, wait / next-check / outcome-check times
CREATE TABLE / INDEX IF NOT EXISTS and a guarded policy: idempotent (prod also runs create_all).

Revision ID: 186
Revises: 185
"""

from alembic import op

revision = "186"
down_revision = "185"
branch_labels = None
depends_on = None

TABLE = "chief_proposals"
COLUMNS = """
    id               VARCHAR PRIMARY KEY,
    tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
    finding_id       VARCHAR NOT NULL REFERENCES insights(id),
    code             VARCHAR(10) NOT NULL,
    target_id        VARCHAR,
    title            VARCHAR(255) NOT NULL,
    why              TEXT NOT NULL,
    risk_tier        VARCHAR(4) NOT NULL,
    preview          JSON NOT NULL,
    steps            JSON NOT NULL,
    plan_sha         VARCHAR(64) NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'awaiting_approval',
    step_index       INTEGER NOT NULL DEFAULT 0,
    decided_by       VARCHAR REFERENCES users(id),
    decided_at       TIMESTAMP WITH TIME ZONE,
    decided_via      VARCHAR(10),
    decision_reason  VARCHAR(20),
    decision_note    TEXT,
    baseline         JSON,
    next_check_at    TIMESTAMP WITH TIME ZONE,
    wait_until       TIMESTAMP WITH TIME ZONE,
    finished_at      TIMESTAMP WITH TIME ZONE,
    check_due_at     TIMESTAMP WITH TIME ZONE,
    failure          TEXT,
    outcome          JSON,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
"""
OPEN = "status IN ('awaiting_approval','approved','executing','waiting')"


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} ({COLUMNS})")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_status ON {TABLE} (tenant_id, status)")
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{TABLE}_open_finding ON {TABLE} (tenant_id, finding_id) WHERE {OPEN}"
    )
    if postgres:
        op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = '{TABLE}' AND policyname = '{TABLE}_tenant_isolation'
                ) THEN
                    CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
