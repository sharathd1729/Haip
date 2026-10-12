"""PROPOSED -- not applied, not in alembic/versions on purpose.

Enable row-level security on the tenant-scoped tables the Phase 0 audit found without any RLS statement.

Why it lives here: the API container runs ``alembic upgrade head`` on start, so a file in
``alembic/versions`` is applied by the next deploy. This one must not be applied until the release
checks in docs/HAIP_Phase0_Production_Checklist.md pass (above all: which database role the app
connects as, and whether any query on these tables runs without ``set_tenant_context``).
To promote it: ``git mv alembic/proposed/118_rls_remaining_tenant_tables.py alembic/versions/``.

What it does, per table, only if the table exists (``saved_views`` has no create-table migration
and exists only where ``create_all`` made it):

  * ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY``
  * ``CREATE POLICY <table>_tenant_isolation ... USING (tenant_id = current_setting('app.tenant_id', true)::text)``

It deliberately does NOT ``FORCE`` row-level security. Without FORCE the table owner (and any role with
BYPASSRLS) is unaffected, so applying it cannot change behaviour for the connection the app uses today;
it only protects connections made through a restricted role. Moving to FORCE is a separate step that
requires auditing every query that runs without a tenant context (Celery cross-tenant fan-outs, webhook
lookups before the tenant is known), because under FORCE such a query silently returns no rows.

Left out on purpose:
  * users, refresh_tokens, user_invitations, oauth_grants, personal_access_tokens -- resolved before the
    tenant is known (sign-in, refresh, invitation accept, bearer lookup), so a plain tenant policy would break
    authentication. They need the SECURITY DEFINER lookup-function pattern used by api_keys (migration 112) first.
  * grievances -- a public, unauthenticated intake form; tenant_id is NULLABLE (NULL = platform-level grievance),
    so ``tenant_id = current_setting(...)`` would hide or reject exactly those rows. Needs its own policy design
    (e.g. permit INSERT with a NULL tenant, restrict SELECT/UPDATE to the tenant).

Every statement is idempotent: production builds tables with create_all, so the table or the policy may
already exist.

Revision ID: 118
Revises: 117
"""
from alembic import op

revision = "118"
down_revision = "117"
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "guest_identities",    # PII: phone/email/Instagram ids per guest
    "inquiry_quotes",
    "inquiry_stage_log",
    "automation_rules",
    "automation_runs",
    "insights",
    "saved_views",
    "blocked_dates",
    "property_addons",
    "seasonal_rates",
    # Found by the PostgreSQL guard test (tests/test_rls_postgres.py) on a database built by alembic;
    # a model-based static scan had missed them.
    "consent_log",                    # DPDP consent records (no application code reads it today)
    "incidents",
    "instagram_insights_snapshots",   # written by a cross-tenant Celery fan-out: audit before any FORCE
    "instagram_post_snapshots",       # same
    "stays_date_quarantine",          # migration 071 snapshot of stays whose dates could not be parsed
    "meta_quality_snapshots",         # inline model in meta_quality_poll.py; exists only where create_all imported it
]

_ARRAY = ", ".join(f"'{t}'" for t in TENANT_TABLES)

UPGRADE_SQL = f"""
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[{_ARRAY}] LOOP
        IF to_regclass('public.' || t) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE tablename = t AND policyname = t || '_tenant_isolation'
            ) THEN
                EXECUTE format(
                    'CREATE POLICY %I ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)::text)',
                    t || '_tenant_isolation', t
                );
            END IF;
        END IF;
    END LOOP;
END
$$
"""

DOWNGRADE_SQL = f"""
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[{_ARRAY}] LOOP
        IF to_regclass('public.' || t) IS NOT NULL THEN
            EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_tenant_isolation', t);
            EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t);
        END IF;
    END LOOP;
END
$$
"""


def upgrade():
    op.execute(UPGRADE_SQL)


def downgrade():
    op.execute(DOWNGRADE_SQL)
