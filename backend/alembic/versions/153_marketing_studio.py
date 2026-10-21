"""Marketing Studio, Phase 1 (docs/marketing-website/PHASE0_AUDIT.md).

New tables only; nothing existing is altered:
  * media_assets, usage_events (shared platform: media library, metered usage)
  * marketing_audits, marketing_plans, marketing_content, marketing_content_versions, marketing_approvals
Every table carries tenant_id NOT NULL and, on PostgreSQL, ENABLE + FORCE row-level security with a tenant policy.

Catalogue rows:
  * module 'marketing_studio' (requires instagram). NOT enabled for any tenant: an owner switches it on
    (POST /workspace/modules/marketing_studio/activate).
  * capabilities marketing.read / marketing.edit / marketing.approve, tied to the module. Provisioned tenants
    (any role_capabilities rows) get the full row set for the three keys, allowed per the default matrix
    (read/edit: owner, manager, marketing; approve: owner, manager — owner decision D3). Existing rows are never
    changed. Unprovisioned tenants are left alone (they keep failing closed).

Idempotent (IF NOT EXISTS, guarded policy, ON CONFLICT / existence checks), because prod also runs create_all at start.
Downgrade drops the new tables and the catalogue rows.

Revision ID: 153
Revises: 152
"""
import logging
import uuid

import sqlalchemy as sa
from alembic import op

revision = "153"
down_revision = "152"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

MODULE = "marketing_studio"
_ROLES = ("owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only")
CAPABILITIES = [
    # key, label, is_write, risk, allowed roles
    ("marketing.read", "View Marketing Studio audits, plans and content", False, "low", {"owner", "manager", "marketing"}),
    ("marketing.edit", "Generate and edit marketing content", True, "medium", {"owner", "manager", "marketing"}),
    ("marketing.approve", "Approve marketing content for publishing", True, "high", {"owner", "manager"}),
]

_TABLES = {
    "media_assets": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        property_id VARCHAR,
        storage_key VARCHAR(300) NOT NULL,
        mime_type VARCHAR(40) NOT NULL,
        bytes INTEGER NOT NULL,
        width INTEGER,
        height INTEGER,
        sha256 VARCHAR(64) NOT NULL,
        alt_text TEXT,
        source VARCHAR(20) NOT NULL DEFAULT 'upload',
        provenance JSON,
        created_by VARCHAR,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "usage_events": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        module VARCHAR(40) NOT NULL,
        kind VARCHAR(40) NOT NULL,
        provider VARCHAR(40),
        model VARCHAR(120),
        units INTEGER NOT NULL DEFAULT 0,
        input_units INTEGER,
        output_units INTEGER,
        ref_type VARCHAR(40),
        ref_id VARCHAR,
        meta JSON,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "marketing_audits": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        channel VARCHAR(20) NOT NULL DEFAULT 'instagram',
        measured JSON NOT NULL,
        assessment JSON,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        error TEXT,
        prompt_version VARCHAR(60),
        model VARCHAR(120),
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "marketing_plans": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        audit_id VARCHAR,
        period_start VARCHAR(10) NOT NULL,
        period_end VARCHAR(10) NOT NULL,
        brief TEXT,
        body JSON,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        error TEXT,
        prompt_version VARCHAR(60),
        model VARCHAR(120),
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "marketing_content": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        kind VARCHAR(20) NOT NULL,
        channel VARCHAR(20) NOT NULL DEFAULT 'instagram',
        title VARCHAR(160) NOT NULL,
        property_id VARCHAR,
        plan_id VARCHAR,
        planned_for VARCHAR(10),
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        current_version_id VARCHAR,
        approved_version_id VARCHAR,
        approved_sha256 VARCHAR(64),
        generation_status VARCHAR(20) NOT NULL DEFAULT 'idle',
        generation_error TEXT,
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "marketing_content_versions": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        content_id VARCHAR NOT NULL REFERENCES marketing_content(id),
        version INTEGER NOT NULL,
        payload JSON NOT NULL,
        sha256 VARCHAR(64) NOT NULL,
        origin VARCHAR(10) NOT NULL,
        note TEXT,
        prompt_version VARCHAR(60),
        model VARCHAR(120),
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_marketing_content_versions_n UNIQUE (content_id, version)
    """,
    "marketing_approvals": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        content_id VARCHAR NOT NULL REFERENCES marketing_content(id),
        version_id VARCHAR NOT NULL,
        sha256 VARCHAR(64) NOT NULL,
        decision VARCHAR(20) NOT NULL,
        note TEXT,
        actor_user_id VARCHAR NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    """,
}

_INDEXES = [
    ("media_assets", "ix_media_assets_tenant_sha", "(tenant_id, sha256)"),
    ("usage_events", "ix_usage_events_tenant_module_created", "(tenant_id, module, created_at)"),
    ("marketing_content", "ix_marketing_content_tenant_status", "(tenant_id, status)"),
    ("marketing_content_versions", "ix_marketing_content_versions_content_id", "(content_id)"),
    ("marketing_approvals", "ix_marketing_approvals_content_id", "(content_id)"),
]


def apply_capabilities(bind) -> dict:
    """Insert catalogue rows and, for provisioned tenants, any missing role cells. Never edits an existing row."""
    result = {"catalogue": 0, "cells": 0}
    for key, label, is_write, risk, _ in CAPABILITIES:
        if bind.execute(sa.text("SELECT 1 FROM capabilities WHERE key = :k"), {"k": key}).first() is None:
            bind.execute(
                sa.text("INSERT INTO capabilities (key, label, category, is_write, module_code, risk) "
                        "VALUES (:k, :l, 'marketing', :w, :m, :r)"),
                {"k": key, "l": label, "w": is_write, "m": MODULE, "r": risk},
            )
            result["catalogue"] += 1
    tenants = [t for (t,) in bind.execute(sa.text("SELECT DISTINCT tenant_id FROM role_capabilities")).all()]
    for tenant_id in tenants:
        present = {
            (r, k) for r, k in bind.execute(
                sa.text("SELECT role, capability_key FROM role_capabilities WHERE tenant_id = :t AND capability_key LIKE 'marketing.%'"),
                {"t": tenant_id},
            ).all()
        }
        for key, _, _, _, allowed_roles in CAPABILITIES:
            for role in _ROLES:
                if (role, key) in present:
                    continue
                bind.execute(
                    sa.text("INSERT INTO role_capabilities (id, tenant_id, role, capability_key, allowed, created_at, updated_at) "
                            "VALUES (:id, :t, :r, :k, :a, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                    {"id": str(uuid.uuid4()), "t": tenant_id, "r": role, "k": key, "a": role in allowed_roles},
                )
                result["cells"] += 1
    return result


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, cols in _TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
    for table, name, cols in _INDEXES:
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
    if bind.execute(sa.text("SELECT 1 FROM modules WHERE code = :c"), {"c": MODULE}).first() is None:
        bind.execute(
            sa.text("INSERT INTO modules (id, code, name, description, category, status, requires_modules) "
                    "VALUES (:id, :c, 'Marketing Studio', :d, 'marketing', 'beta', "
                    + ("CAST(:req AS JSONB))" if postgres else ":req)")),
            {"id": str(uuid.uuid4()), "c": MODULE, "req": '["instagram"]',
             "d": "Social audit, AI strategy and content calendar, AI-drafted posts with owner/manager approval"},
        )
    result = apply_capabilities(bind)
    log.info("129: marketing capabilities -> %s", result)


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM role_capabilities WHERE capability_key LIKE 'marketing.%'"))
    bind.execute(sa.text("DELETE FROM capabilities WHERE key LIKE 'marketing.%'"))
    bind.execute(sa.text("DELETE FROM workspace_modules WHERE module_id IN (SELECT id FROM modules WHERE code = 'marketing_studio')"))
    bind.execute(sa.text("DELETE FROM modules WHERE code = 'marketing_studio'"))
    for table in ("marketing_approvals", "marketing_content_versions", "marketing_content",
                  "marketing_plans", "marketing_audits", "usage_events", "media_assets"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
