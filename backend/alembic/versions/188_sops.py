"""Dynamic SOPs, phase S1 (docs/sops/DYNAMIC_SOPS_PLAN.md): sop_instances, sop_versions, sop_step_progress.

Every table has tenant_id NOT NULL and, on PostgreSQL, row-level security enabled + forced with the usual tenant policy.
One live (not archived) instance per (tenant, template, target) is a partial unique index.

Capabilities sops.read / sops.work / sops.manage are added to the catalogue and granted to every PROVISIONED tenant (one
with role_capabilities rows) per the default matrix in authz_service; they are new keys, so no owner has customised them.
No module row: SOPs are guidance only (nothing is sent anywhere), so every workspace has them (owner decision D3).

Numbered 188 because 185-187 belong to the AI Executive branch; it follows 184 (website promo codes, PR #112).
Idempotent (IF NOT EXISTS, guarded policies, existence checks) because production runs create_all at startup.

Revision ID: 188
Revises: 184
"""

import logging
import uuid

import sqlalchemy as sa

from alembic import op

revision = "188"
down_revision = "184"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

_TS = "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"

_TABLES = {
    "sop_instances": f"""
        id                 VARCHAR PRIMARY KEY,
        tenant_id          VARCHAR NOT NULL REFERENCES tenants(id),
        template_key       VARCHAR(60) NOT NULL,
        property_id        VARCHAR REFERENCES properties(id),
        target_key         VARCHAR(64) NOT NULL DEFAULT '',
        status             VARCHAR(12) NOT NULL DEFAULT 'active',
        assignee_id        VARCHAR REFERENCES users(id),
        overrides          JSON,
        current_version_id VARCHAR,
        generating         VARCHAR(12),
        cycle_no           INTEGER NOT NULL DEFAULT 1,
        next_cycle_at      TIMESTAMPTZ,
        started_by         VARCHAR,
        last_done_at       TIMESTAMPTZ,
        {_TS}
    """,
    "sop_versions": f"""
        id               VARCHAR PRIMARY KEY,
        tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
        instance_id      VARCHAR NOT NULL REFERENCES sop_instances(id) ON DELETE CASCADE,
        version_no       INTEGER NOT NULL,
        template_version INTEGER NOT NULL,
        rules_digest     VARCHAR(64) NOT NULL,
        inputs_sha       VARCHAR(64) NOT NULL,
        steps            JSON NOT NULL,
        reason           VARCHAR(20) NOT NULL,
        model            VARCHAR(120),
        prompt_version   VARCHAR(60),
        ai_note          TEXT,
        created_by       VARCHAR,
        {_TS},
        CONSTRAINT uq_sop_versions_no UNIQUE (instance_id, version_no)
    """,
    "sop_step_progress": f"""
        id                VARCHAR PRIMARY KEY,
        tenant_id         VARCHAR NOT NULL REFERENCES tenants(id),
        instance_id       VARCHAR NOT NULL REFERENCES sop_instances(id) ON DELETE CASCADE,
        cycle_no          INTEGER NOT NULL DEFAULT 1,
        step_key          VARCHAR(40) NOT NULL,
        step_sha          VARCHAR(64),
        status            VARCHAR(16) NOT NULL DEFAULT 'todo',
        due_at            TIMESTAMPTZ,
        done_by           VARCHAR,
        done_at           TIMESTAMPTZ,
        evidence_asset_id VARCHAR,
        evidence_url      VARCHAR(500),
        check_result      JSON,
        task_id           VARCHAR,
        reminder_level    INTEGER NOT NULL DEFAULT 0,
        {_TS},
        CONSTRAINT uq_sop_step_progress UNIQUE (instance_id, cycle_no, step_key)
    """,
}

_INDEXES = [
    ("ix_sop_versions_instance_id", "sop_versions", "(instance_id)"),
    ("ix_sop_step_progress_instance_id", "sop_step_progress", "(instance_id)"),
]

CAPABILITIES = [
    # key, label, is_write, risk, roles granted by default (= authz_service._DEFAULT_GRANTS)
    (
        "sops.read",
        "See the Get found checklists (SOPs)",
        False,
        "low",
        ("owner", "manager", "marketing", "reservations", "concierge", "foh"),
    ),
    ("sops.work", "Tick SOP steps, add screenshots and run checks", True, "low", ("owner", "manager", "marketing")),
    ("sops.manage", "Start, assign, customise and regenerate SOPs", True, "medium", ("owner", "manager")),
]
ROLES = ("owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only")


def grant_capabilities(bind) -> dict:
    """Add the SOP capabilities to the catalogue and insert missing role rows for provisioned tenants. Safe to repeat."""
    result = {"catalogue_added": 0, "rows_inserted": 0}
    for key, label, is_write, risk, _ in CAPABILITIES:
        if bind.execute(sa.text("SELECT 1 FROM capabilities WHERE key = :k"), {"k": key}).first() is None:
            bind.execute(
                sa.text(
                    "INSERT INTO capabilities (key, label, category, is_write, module_code, risk) "
                    "VALUES (:k, :l, 'sops', :w, NULL, :r)"
                ),
                {"k": key, "l": label, "w": is_write, "r": risk},
            )
            result["catalogue_added"] += 1
    tenants = [t for (t,) in bind.execute(sa.text("SELECT DISTINCT tenant_id FROM role_capabilities")).all()]
    for tenant_id in tenants:
        existing = {
            (r, k)
            for r, k in bind.execute(
                sa.text(
                    "SELECT role, capability_key FROM role_capabilities WHERE tenant_id = :t AND capability_key LIKE 'sops.%'"
                ),
                {"t": tenant_id},
            ).all()
        }
        for key, _, _, _, granted in CAPABILITIES:
            for role in ROLES:
                if (role, key) in existing:
                    continue
                bind.execute(
                    sa.text(
                        "INSERT INTO role_capabilities (id, tenant_id, role, capability_key, allowed, created_at, updated_at) "
                        "VALUES (:id, :t, :r, :k, :a, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"id": str(uuid.uuid4()), "t": tenant_id, "r": role, "k": key, "a": role in granted},
                )
                result["rows_inserted"] += 1
    return result


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
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sop_instances_live ON sop_instances (tenant_id, template_key, target_key) "
        "WHERE status <> 'archived'"
    )
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
    log.info("188: sop capabilities -> %s", grant_capabilities(bind))


def downgrade():
    for table in reversed(list(_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM role_capabilities WHERE capability_key IN ('sops.read', 'sops.work', 'sops.manage')")
    )
    bind.execute(sa.text("DELETE FROM capabilities WHERE key IN ('sops.read', 'sops.work', 'sops.manage')"))
