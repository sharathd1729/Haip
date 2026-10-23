"""AI business analyst + learning loop: analyst_reports, agent_experiments, agent_experiment_assignments, agent_lessons

Four tenant tables, each tenant_id NOT NULL with ENABLE + FORCE row-level security and a tenant policy. A partial unique index
keeps at most one RUNNING experiment per control (no overlapping tests on the same setting). Settings live in brand_config
(analyst / learning), so no other schema change. Production builds tables with create_all at startup (no RLS), so every
statement is guarded and the migration is idempotent. Downgrade drops only these four tables.

171 belongs to feat/lead-evidence-outcomes (inquiries.outcome_reason ...); this revision hangs off 170 and a merge revision
joins the two when both land.

Revision ID: 172
Revises: 170
Create Date: 2026-10-23
"""
from alembic import op

revision = "172"
down_revision = "170"
branch_labels = None
depends_on = None

TABLES = ("analyst_reports", "agent_experiments", "agent_experiment_assignments", "agent_lessons")


def _rls(table: str) -> None:
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


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS analyst_reports (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL,
            kind            VARCHAR(20) NOT NULL,
            period_start    DATE NOT NULL,
            period_end      DATE NOT NULL,
            status          VARCHAR(12) NOT NULL DEFAULT 'ready',
            facts           JSON NOT NULL DEFAULT '{}',
            brief           JSON NOT NULL DEFAULT '{}',
            brief_source    VARCHAR(16) NOT NULL DEFAULT 'deterministic',
            validation      JSON NOT NULL DEFAULT '{}',
            model           VARCHAR(120),
            prompt_version  VARCHAR(60),
            followups       JSON NOT NULL DEFAULT '[]',
            delivery        JSON NOT NULL DEFAULT '{}',
            created_by      VARCHAR,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_analyst_reports_tenant_id ON analyst_reports (tenant_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_analyst_reports_period ON analyst_reports (tenant_id, kind, period_start)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_analyst_reports_tenant_kind_created ON analyst_reports (tenant_id, kind, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_experiments (
            id                   VARCHAR PRIMARY KEY,
            tenant_id            VARCHAR NOT NULL,
            change_type          VARCHAR(40) NOT NULL,
            area                 VARCHAR(20) NOT NULL,
            control              VARCHAR(40) NOT NULL,
            title                VARCHAR(300) NOT NULL,
            rationale            JSON NOT NULL DEFAULT '{}',
            diff                 JSON NOT NULL DEFAULT '{}',
            target_metric        VARCHAR(30) NOT NULL,
            min_sample_per_arm   INTEGER NOT NULL DEFAULT 40,
            max_days             INTEGER NOT NULL DEFAULT 14,
            stop_loss            JSON NOT NULL DEFAULT '{}',
            status               VARCHAR(20) NOT NULL DEFAULT 'proposed',
            assignment_rule      JSON NOT NULL DEFAULT '{}',
            metrics              JSON NOT NULL DEFAULT '{}',
            decision             JSON NOT NULL DEFAULT '{}',
            decided_by           VARCHAR(10),
            decided_by_user_id   VARCHAR,
            bench                JSON NOT NULL DEFAULT '{}',
            applied_before       JSON,
            applied_after        JSON,
            source_report_id     VARCHAR,
            proposed_by          VARCHAR,
            approved_by          VARCHAR,
            approved_at          TIMESTAMPTZ,
            started_at           TIMESTAMPTZ,
            ended_at             TIMESTAMPTZ,
            undone_at            TIMESTAMPTZ,
            undone_by            VARCHAR,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_experiments_tenant_id ON agent_experiments (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_experiments_tenant_status ON agent_experiments (tenant_id, status)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_experiments_running_control
        ON agent_experiments (tenant_id, control) WHERE status = 'running'
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_experiment_assignments (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL,
            experiment_id    VARCHAR NOT NULL REFERENCES agent_experiments(id),
            conversation_id  VARCHAR NOT NULL,
            guest_id         VARCHAR,
            arm              VARCHAR(10) NOT NULL,
            guest_was_lead   BOOLEAN NOT NULL DEFAULT false,
            assigned_at      TIMESTAMPTZ NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_experiment_assignments_tenant_id ON agent_experiment_assignments (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_experiment_assignments_experiment_id ON agent_experiment_assignments (experiment_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_experiment_assignments_conversation_id ON agent_experiment_assignments (conversation_id)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_experiment_assignments_conv
        ON agent_experiment_assignments (experiment_id, conversation_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_agent_experiment_assignments_guest
        ON agent_experiment_assignments (tenant_id, experiment_id, guest_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_lessons (
            id                    VARCHAR PRIMARY KEY,
            tenant_id             VARCHAR NOT NULL,
            text                  TEXT NOT NULL,
            metric                VARCHAR(30) NOT NULL,
            change_type           VARCHAR(40),
            effect_size           DOUBLE PRECISION,
            sample                INTEGER NOT NULL DEFAULT 0,
            period_start          DATE,
            period_end            DATE,
            source_experiment_id  VARCHAR,
            source_report_id      VARCHAR,
            status                VARCHAR(10) NOT NULL DEFAULT 'active',
            retired_reason        TEXT,
            retired_at            TIMESTAMPTZ,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_lessons_tenant_id ON agent_lessons (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_lessons_tenant_status ON agent_lessons (tenant_id, status)")

    for table in TABLES:
        _rls(table)


def downgrade():
    op.execute("DROP TABLE IF EXISTS agent_lessons")
    op.execute("DROP TABLE IF EXISTS agent_experiment_assignments")
    op.execute("DROP TABLE IF EXISTS agent_experiments")
    op.execute("DROP TABLE IF EXISTS analyst_reports")
