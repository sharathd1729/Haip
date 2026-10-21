"""Website builder (docs/website-builder/README.md).

New tables only; nothing existing is altered:
  * sites                 one guest-facing website per tenant (settings that are NOT versioned: booking mode, deposit)
  * site_versions         the whole site document (theme, pages, blocks) as JSON; immutable once submitted
  * site_domains          hostnames (a free subdomain + custom domains) -> site; looked up by website_host_lookup()
  * booking_holds         a guest's dates held for N minutes while they pay; counted as taken by the website
  * guest_access_tokens   hashed "My booking" magic-link tokens
  * site_ai_jobs          AI generate / edit / rewrite / SEO jobs (Celery), with the JSON result
  * site_page_views       daily page-view counters per path and source (no cookies)
Every table carries tenant_id NOT NULL and, on PostgreSQL, ENABLE + FORCE row-level security with a tenant policy.

website_host_lookup(host) is SECURITY DEFINER (like api_key_lookup in 112): a guest request has no tenant yet, so
the hostname -> (site, tenant) step runs without RLS and returns only those two ids; every later read sets the
tenant context and goes through RLS.

Catalogue rows: module 'website' (NOT enabled for any tenant: an owner switches it on) and capabilities
website.read / website.edit / website.approve (read/edit: owner, manager, marketing; approve: owner, manager), added
for provisioned tenants without touching existing cells.

Idempotent (IF NOT EXISTS, guarded policy, existence checks), because prod also runs create_all at start.

Revision ID: 158
Revises: 157
"""
import logging
import uuid

import sqlalchemy as sa
from alembic import op

revision = "158"
down_revision = "157"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

MODULE = "website"
_ROLES = ("owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only")
CAPABILITIES = [
    ("website.read", "View the website, its pages and versions", False, "low", {"owner", "manager", "marketing"}),
    ("website.edit", "Edit website drafts and ask the AI developer", True, "medium", {"owner", "manager", "marketing"}),
    ("website.approve", "Approve and publish website versions", True, "high", {"owner", "manager"}),
]

_TABLES = {
    "sites": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        name VARCHAR(160) NOT NULL,
        slug VARCHAR(63) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        settings JSON,
        draft_version_id VARCHAR,
        live_version_id VARCHAR,
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_sites_slug UNIQUE (slug)
    """,
    "site_versions": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        site_id VARCHAR NOT NULL REFERENCES sites(id),
        number INTEGER NOT NULL,
        doc JSON NOT NULL,
        sha256 VARCHAR(64) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        origin VARCHAR(10) NOT NULL DEFAULT 'human',
        note TEXT,
        created_by VARCHAR,
        submitted_by VARCHAR,
        submitted_at TIMESTAMPTZ,
        approved_by VARCHAR,
        approved_at TIMESTAMPTZ,
        published_by VARCHAR,
        published_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_site_versions_number UNIQUE (site_id, number)
    """,
    "site_domains": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        site_id VARCHAR NOT NULL REFERENCES sites(id),
        hostname VARCHAR(253) NOT NULL,
        kind VARCHAR(12) NOT NULL DEFAULT 'custom',
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        verify_token VARCHAR(64) NOT NULL,
        provider_ref VARCHAR(120),
        error TEXT,
        last_checked_at TIMESTAMPTZ,
        verified_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_site_domains_hostname UNIQUE (hostname)
    """,
    "booking_holds": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        site_id VARCHAR NOT NULL REFERENCES sites(id),
        property_id VARCHAR NOT NULL,
        check_in DATE NOT NULL,
        check_out DATE NOT NULL,
        adults INTEGER NOT NULL DEFAULT 1,
        children INTEGER NOT NULL DEFAULT 0,
        mode VARCHAR(12) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'held',
        quote JSON NOT NULL,
        total NUMERIC(12, 2) NOT NULL,
        pay_now NUMERIC(12, 2) NOT NULL DEFAULT 0,
        gst_percent NUMERIC(5, 2),
        guest_details JSON,
        session_hash VARCHAR(64) NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        guest_id VARCHAR,
        inquiry_id VARCHAR,
        stay_id VARCHAR,
        payment_link_id VARCHAR(64),
        payment_url TEXT,
        payment_id VARCHAR(64),
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "guest_access_tokens": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        stay_id VARCHAR NOT NULL,
        token_hash VARCHAR(64) NOT NULL,
        purpose VARCHAR(20) NOT NULL DEFAULT 'manage',
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_guest_access_tokens_hash UNIQUE (token_hash)
    """,
    "site_ai_jobs": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        site_id VARCHAR NOT NULL REFERENCES sites(id),
        kind VARCHAR(20) NOT NULL,
        request TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        result JSON,
        error TEXT,
        base_version_id VARCHAR,
        result_version_id VARCHAR,
        prompt_version VARCHAR(60),
        model VARCHAR(120),
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "site_page_views": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        site_id VARCHAR NOT NULL REFERENCES sites(id),
        day VARCHAR(10) NOT NULL,
        path VARCHAR(200) NOT NULL,
        source VARCHAR(60) NOT NULL DEFAULT 'direct',
        views INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_site_page_views_key UNIQUE (site_id, day, path, source)
    """,
}

_INDEXES = [
    ("site_versions", "ix_site_versions_site_id", "(site_id)"),
    ("site_domains", "ix_site_domains_site_id", "(site_id)"),
    ("booking_holds", "ix_booking_holds_tenant_property_status", "(tenant_id, property_id, status)"),
    ("booking_holds", "ix_booking_holds_payment_link_id", "(payment_link_id)"),
    ("guest_access_tokens", "ix_guest_access_tokens_stay_id", "(stay_id)"),
    ("site_ai_jobs", "ix_site_ai_jobs_site_id", "(site_id)"),
]

_LOOKUP_FN = """
CREATE OR REPLACE FUNCTION website_host_lookup(p_host text)
RETURNS TABLE (site_id text, tenant_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT d.site_id::text, d.tenant_id::text FROM site_domains d
   WHERE d.hostname = lower(p_host) AND d.status IN ('verified', 'active') LIMIT 1 $$
"""


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
                sa.text("SELECT role, capability_key FROM role_capabilities WHERE tenant_id = :t AND capability_key LIKE 'website.%'"),
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
        op.execute(_LOOKUP_FN)
    if bind.execute(sa.text("SELECT 1 FROM modules WHERE code = :c"), {"c": MODULE}).first() is None:
        bind.execute(
            sa.text("INSERT INTO modules (id, code, name, description, category, status, requires_modules) "
                    "VALUES (:id, :c, 'Website', :d, 'marketing', 'beta', "
                    + ("CAST(:req AS JSONB))" if postgres else ":req)")),
            {"id": str(uuid.uuid4()), "c": MODULE, "req": "[]",
             "d": "A complete, bookable website built and hosted by HAIP, edited by the owner and an AI web developer"},
        )
    result = apply_capabilities(bind)
    log.info("158: website capabilities -> %s", result)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS website_host_lookup(text)")
    bind.execute(sa.text("DELETE FROM role_capabilities WHERE capability_key LIKE 'website.%'"))
    bind.execute(sa.text("DELETE FROM capabilities WHERE key LIKE 'website.%'"))
    bind.execute(sa.text("DELETE FROM workspace_modules WHERE module_id IN (SELECT id FROM modules WHERE code = 'website')"))
    bind.execute(sa.text("DELETE FROM modules WHERE code = 'website'"))
    for table in ("site_page_views", "site_ai_jobs", "guest_access_tokens", "booking_holds",
                  "site_domains", "site_versions", "sites"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
