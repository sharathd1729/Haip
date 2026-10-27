"""Operations module foundations: staff, shift roster, escalation chains, ops items, alert sends (docs/ops/OPS_MODULE_PLAN.md).

New tables only; nothing existing is altered. Every table has tenant_id NOT NULL and, on PostgreSQL, row-level security
enabled + forced with the usual tenant policy. Idempotent (IF NOT EXISTS, guarded policies, insert-if-missing grants) because
production runs create_all at startup.

Also adds three capabilities to the catalogue and grants them to every PROVISIONED tenant (one that already has
role_capabilities rows). They are brand-new keys, so no owner can have customised them; unprovisioned tenants stay untouched
(fail closed). Defaults mirror authz_service._DEFAULT_GRANTS:
  ops.read   owner, manager, reservations, concierge, foh
  ops.write  owner, manager, concierge, foh
  ops.manage owner, manager

Numbering: written as 131 on feat/ops-foundations (on 128) and renumbered 178 onto head 177 when it merged.

Revision ID: 178
Revises: 177
"""

import logging
import uuid

import sqlalchemy as sa

from alembic import op

revision = "178"
down_revision = "177"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

_TABLES = {
    "staff_profiles": """
        id                 VARCHAR PRIMARY KEY,
        tenant_id          VARCHAR NOT NULL REFERENCES tenants(id),
        user_id            VARCHAR REFERENCES users(id),
        name               VARCHAR(120) NOT NULL,
        phone_e164         VARCHAR(20) NOT NULL,
        languages          JSON,
        whatsapp_opt_in_at TIMESTAMPTZ,
        active             BOOLEAN NOT NULL DEFAULT TRUE,
        notes              TEXT,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_staff_profiles_phone UNIQUE (tenant_id, phone_e164)
    """,
    "staff_duties": """
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        staff_id    VARCHAR NOT NULL REFERENCES staff_profiles(id) ON DELETE CASCADE,
        duty        VARCHAR(30) NOT NULL,
        property_id VARCHAR REFERENCES properties(id),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "shift_patterns": """
        id           VARCHAR PRIMARY KEY,
        tenant_id    VARCHAR NOT NULL REFERENCES tenants(id),
        staff_id     VARCHAR NOT NULL REFERENCES staff_profiles(id) ON DELETE CASCADE,
        duty         VARCHAR(30) NOT NULL,
        property_id  VARCHAR REFERENCES properties(id),
        weekday      INTEGER NOT NULL,
        start_minute INTEGER NOT NULL,
        end_minute   INTEGER NOT NULL,
        active       BOOLEAN NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "shift_overrides": """
        id                   VARCHAR PRIMARY KEY,
        tenant_id            VARCHAR NOT NULL REFERENCES tenants(id),
        staff_id             VARCHAR NOT NULL REFERENCES staff_profiles(id) ON DELETE CASCADE,
        kind                 VARCHAR(10) NOT NULL,
        starts_at            TIMESTAMPTZ NOT NULL,
        ends_at              TIMESTAMPTZ NOT NULL,
        duty                 VARCHAR(30),
        property_id          VARCHAR REFERENCES properties(id),
        replacement_staff_id VARCHAR REFERENCES staff_profiles(id),
        note                 TEXT,
        created_by           VARCHAR,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "escalation_chains": """
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        duty        VARCHAR(30) NOT NULL,
        property_id VARCHAR REFERENCES properties(id),
        steps       JSON NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "ops_settings": """
        id                VARCHAR PRIMARY KEY,
        tenant_id         VARCHAR NOT NULL UNIQUE REFERENCES tenants(id),
        alerts_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
        sla               JSON,
        quiet_hours       JSON,
        templates         JSON,
        template_language VARCHAR(10) NOT NULL DEFAULT 'en',
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "ops_items": """
        id                       VARCHAR PRIMARY KEY,
        tenant_id                VARCHAR NOT NULL REFERENCES tenants(id),
        kind                     VARCHAR(20) NOT NULL,
        title                    VARCHAR(200) NOT NULL,
        summary                  TEXT,
        category                 VARCHAR(30),
        severity                 VARCHAR(10) NOT NULL,
        duty                     VARCHAR(30) NOT NULL,
        status                   VARCHAR(15) NOT NULL DEFAULT 'open',
        source                   VARCHAR(20) NOT NULL DEFAULT 'staff',
        property_id              VARCHAR REFERENCES properties(id),
        stay_id                  VARCHAR REFERENCES stays(id),
        guest_id                 VARCHAR REFERENCES guests(id),
        conversation_id          VARCHAR,
        service_request_id       VARCHAR,
        current_step             INTEGER NOT NULL DEFAULT 0,
        dispatched_step          INTEGER,
        dispatch_after           TIMESTAMPTZ,
        step_started_at          TIMESTAMPTZ,
        ack_due_at               TIMESTAMPTZ,
        resolve_due_at           TIMESTAMPTZ,
        resolve_breached_at      TIMESTAMPTZ,
        repeat_count             INTEGER NOT NULL DEFAULT 0,
        escalation_exhausted     BOOLEAN NOT NULL DEFAULT FALSE,
        acknowledged_at          TIMESTAMPTZ,
        acknowledged_by_staff_id VARCHAR,
        acknowledged_by_user_id  VARCHAR,
        resolved_at              TIMESTAMPTZ,
        resolved_by_staff_id     VARCHAR,
        resolved_by_user_id      VARCHAR,
        resolution_note          TEXT,
        created_by               VARCHAR,
        created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "ops_escalation_events": """
        id             VARCHAR PRIMARY KEY,
        tenant_id      VARCHAR NOT NULL REFERENCES tenants(id),
        item_id        VARCHAR NOT NULL REFERENCES ops_items(id) ON DELETE CASCADE,
        event          VARCHAR(30) NOT NULL,
        step           INTEGER,
        actor_staff_id VARCHAR,
        actor_user_id  VARCHAR,
        detail         JSON,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "ops_alert_sends": """
        id         VARCHAR PRIMARY KEY,
        tenant_id  VARCHAR NOT NULL REFERENCES tenants(id),
        item_id    VARCHAR NOT NULL REFERENCES ops_items(id) ON DELETE CASCADE,
        step       INTEGER NOT NULL,
        staff_id   VARCHAR,
        user_id    VARCHAR,
        phone_e164 VARCHAR(20),
        channel    VARCHAR(10) NOT NULL,
        template   VARCHAR(80),
        wamid      VARCHAR(128) UNIQUE,
        status     VARCHAR(12) NOT NULL DEFAULT 'queued',
        error      TEXT,
        nonce      VARCHAR(32),
        response   VARCHAR(12),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
}

_INDEXES = [
    ("ix_staff_duties_staff", "staff_duties", "(staff_id)"),
    ("ix_shift_patterns_staff", "shift_patterns", "(staff_id)"),
    ("ix_shift_patterns_lookup", "shift_patterns", "(tenant_id, duty, weekday)"),
    ("ix_shift_overrides_window", "shift_overrides", "(tenant_id, starts_at, ends_at)"),
    ("ix_ops_items_open", "ops_items", "(tenant_id, status)"),
    ("ix_ops_escalation_events_item", "ops_escalation_events", "(item_id)"),
    ("ix_ops_alert_sends_item", "ops_alert_sends", "(item_id)"),
]

CAPABILITIES = [
    # key, label, is_write, risk, roles granted by default
    (
        "ops.read",
        "View operations items, roster and who is on duty",
        False,
        "low",
        ("owner", "manager", "reservations", "concierge", "foh"),
    ),
    (
        "ops.write",
        "Raise, acknowledge and resolve operations items",
        True,
        "medium",
        ("owner", "manager", "concierge", "foh"),
    ),
    (
        "ops.manage",
        "Manage staff, shift roster, escalation chains and ops settings",
        True,
        "high",
        ("owner", "manager"),
    ),
]
ROLES = (
    "owner",
    "manager",
    "reservations",
    "concierge",
    "foh",
    "marketing",
    "compliance",
    "read_only",
)


def grant_capabilities(bind) -> dict:
    """Add the ops capabilities to the catalogue and insert missing role rows for provisioned tenants. Safe to repeat."""
    result = {"catalogue_added": 0, "rows_inserted": 0}
    for key, label, is_write, risk, _ in CAPABILITIES:
        if bind.execute(sa.text("SELECT 1 FROM capabilities WHERE key = :k"), {"k": key}).first() is None:
            bind.execute(
                sa.text(
                    "INSERT INTO capabilities (key, label, category, is_write, module_code, risk) "
                    "VALUES (:k, :l, 'ops', :w, NULL, :r)"
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
                    "SELECT role, capability_key FROM role_capabilities WHERE tenant_id = :t AND capability_key LIKE 'ops.%'"
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
                    {
                        "id": str(uuid.uuid4()),
                        "t": tenant_id,
                        "r": role,
                        "k": key,
                        "a": role in granted,
                    },
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
    result = grant_capabilities(bind)
    log.info("131: ops capabilities -> %s", result)


def downgrade():
    for table in reversed(list(_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM role_capabilities WHERE capability_key IN ('ops.read', 'ops.write', 'ops.manage')")
    )
    bind.execute(sa.text("DELETE FROM capabilities WHERE key IN ('ops.read', 'ops.write', 'ops.manage')"))
