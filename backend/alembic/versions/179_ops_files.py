"""Ops files: one per booking, jobs and photo checklists, trip expenses and extras (Ops module phase 1, caravan pack first).

New tables only; nothing existing is altered. Every table has tenant_id NOT NULL and, on PostgreSQL, row-level security
enabled + forced with the usual tenant policy. Idempotent (IF NOT EXISTS, guarded policies) because production runs
create_all at startup. Uses the ops.read / ops.write / ops.manage capabilities from 178; no new grants.

Revision ID: 179
Revises: 178
"""

from alembic import op

revision = "179"
down_revision = "178"
branch_labels = None
depends_on = None

_TS = "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"

_TABLES = {
    "ops_files": f"""
        id                 VARCHAR PRIMARY KEY,
        tenant_id          VARCHAR NOT NULL REFERENCES tenants(id),
        stay_id            VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
        pack               VARCHAR(30) NOT NULL,
        state              VARCHAR(20) NOT NULL,
        details            JSON NOT NULL,
        accepted_at        TIMESTAMPTZ, accepted_by VARCHAR,
        dispatched_at      TIMESTAMPTZ, dispatched_by VARCHAR,
        returned_at        TIMESTAMPTZ,
        return_checked_at  TIMESTAMPTZ, return_checked_by VARCHAR,
        report_approved_at TIMESTAMPTZ, report_approved_by VARCHAR,
        closed_at          TIMESTAMPTZ, closed_by VARCHAR,
        {_TS},
        CONSTRAINT uq_ops_files_stay UNIQUE (stay_id)
    """,
    "ops_file_events": """
        id        VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        file_id   VARCHAR NOT NULL REFERENCES ops_files(id) ON DELETE CASCADE,
        at        TIMESTAMPTZ NOT NULL,
        text      TEXT NOT NULL,
        auto      BOOLEAN NOT NULL DEFAULT FALSE,
        actor_id  VARCHAR
    """,
    "ops_checklist_templates": f"""
        id        VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        pack      VARCHAR(30) NOT NULL,
        kind      VARCHAR(20) NOT NULL,
        name      VARCHAR(120) NOT NULL,
        items     JSON NOT NULL,
        active    BOOLEAN NOT NULL DEFAULT TRUE,
        {_TS},
        CONSTRAINT uq_ops_checklist_templates_kind UNIQUE (tenant_id, pack, kind)
    """,
    "ops_jobs": f"""
        id           VARCHAR PRIMARY KEY,
        tenant_id    VARCHAR NOT NULL REFERENCES tenants(id),
        file_id      VARCHAR REFERENCES ops_files(id) ON DELETE CASCADE,
        property_id  VARCHAR REFERENCES properties(id),
        kind         VARCHAR(20) NOT NULL,
        template_id  VARCHAR,
        staff_id     VARCHAR REFERENCES staff_profiles(id),
        due_at       TIMESTAMPTZ,
        status       VARCHAR(12) NOT NULL DEFAULT 'open',
        completed_at TIMESTAMPTZ,
        {_TS}
    """,
    "ops_job_items": f"""
        id              VARCHAR PRIMARY KEY,
        tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
        job_id          VARCHAR NOT NULL REFERENCES ops_jobs(id) ON DELETE CASCADE,
        key             VARCHAR(40) NOT NULL,
        label           VARCHAR(200) NOT NULL,
        critical        BOOLEAN NOT NULL DEFAULT FALSE,
        source          VARCHAR(10) NOT NULL DEFAULT 'staff',
        photo_required  BOOLEAN NOT NULL DEFAULT FALSE,
        status          VARCHAR(10) NOT NULL DEFAULT 'pending',
        note            TEXT,
        photo_key       VARCHAR,
        ai_verdict      JSON,
        set_by_user_id  VARCHAR,
        set_by_staff_id VARCHAR,
        set_at          TIMESTAMPTZ,
        {_TS},
        CONSTRAINT uq_ops_job_items_key UNIQUE (job_id, key)
    """,
    "ops_expenses": f"""
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        file_id     VARCHAR REFERENCES ops_files(id) ON DELETE CASCADE,
        property_id VARCHAR REFERENCES properties(id),
        category    VARCHAR(20) NOT NULL,
        amount      NUMERIC(12, 2) NOT NULL,
        gst_amount  NUMERIC(12, 2),
        vendor      VARCHAR(120),
        bill_date   DATE,
        note        TEXT,
        source      VARCHAR(10) NOT NULL DEFAULT 'manual',
        photo_key   VARCHAR,
        bill_key    VARCHAR(200),
        staff_id    VARCHAR,
        created_by  VARCHAR,
        {_TS},
        CONSTRAINT uq_ops_expenses_bill UNIQUE (tenant_id, bill_key)
    """,
    "ops_extras": f"""
        id            VARCHAR PRIMARY KEY,
        tenant_id     VARCHAR NOT NULL REFERENCES tenants(id),
        file_id       VARCHAR NOT NULL REFERENCES ops_files(id) ON DELETE CASCADE,
        kind          VARCHAR(20) NOT NULL,
        label         VARCHAR(200) NOT NULL,
        amount        NUMERIC(12, 2) NOT NULL,
        status        VARCHAR(10) NOT NULL DEFAULT 'proposed',
        stay_addon_id VARCHAR,
        created_by    VARCHAR,
        decided_by    VARCHAR,
        decided_at    TIMESTAMPTZ,
        {_TS}
    """,
}

_INDEXES = [
    ("ix_ops_files_tenant_state", "ops_files", "(tenant_id, state)"),
    ("ix_ops_file_events_file", "ops_file_events", "(file_id)"),
    ("ix_ops_jobs_file", "ops_jobs", "(file_id)"),
    ("ix_ops_job_items_job", "ops_job_items", "(job_id)"),
    ("ix_ops_expenses_file", "ops_expenses", "(file_id)"),
    ("ix_ops_extras_file", "ops_extras", "(file_id)"),
]


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, cols in _TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
    for name, table, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}")
    if postgres:
        for table in _TABLES:
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


def downgrade():
    for table in reversed(list(_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table}")
