"""PostgreSQL-backed tenant-isolation checks (Phase 0, workstream C).

These need a real PostgreSQL: row-level security does not exist on SQLite, and the rest of the suite
mocks ``set_tenant_context``. They run in the ``tenant-isolation-postgres`` CI job
(.github/workflows/tenant-isolation.yml), which sets ``REQUIRE_POSTGRES_TESTS=1`` so that a missing
database is a FAILURE there, not a silent skip.

Locally on SQLite they are skipped, and the skip reason says why. Execution status as of this commit:
written, **not yet executed against PostgreSQL** (no PostgreSQL was available on the authoring machine).

What is proved, and how:

* every table that has a ``tenant_id`` column has row-level security enabled, or is one of the
  documented exceptions below (tables looked up *before* the tenant is known, e.g. sign-in);
* the proposed migration (alembic/proposed/118_*) applies cleanly, is idempotent, and its policy
  actually isolates tenants for a role that does not bypass RLS;
* ``set_tenant_context`` is transaction-local on a real server (it must not leak to the next request
  that reuses the pooled connection).

The probe role is NOLOGIN and has no BYPASSRLS; the connecting CI user is a superuser, so every check
that matters switches to the probe role with ``SET LOCAL ROLE``.
"""
import importlib.util
import os
import pathlib
import uuid

import pytest
from sqlalchemy import text

from tests.conftest import TestingSessionLocal, engine

# meta_quality_snapshots is an inline model that only exists in the metadata (and so in create_all) once its
# module is imported. Importing it here makes the "every tenant table has RLS" guard see the same tables in a
# focused run as in a full-suite run; without this the guard passed alone and failed in the full suite.
import app.workers.tasks.meta_quality_poll  # noqa: F401,E402

IS_POSTGRES = engine.dialect.name == "postgresql"
REQUIRED = os.environ.get("REQUIRE_POSTGRES_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not IS_POSTGRES and not REQUIRED,
    reason="PostgreSQL-backed (row-level security); DATABASE_URL is not PostgreSQL. Runs in CI job tenant-isolation-postgres.",
)

PROBE_ROLE = "haip_rls_probe"

# Tables with a tenant_id column that intentionally have NO row-level security, because they are read
# before the tenant is known (sign-in, token refresh, invitation accept, OAuth/PAT bearer lookup) or are written by anonymous
# visitors with an optional tenant (grievances).
# Protecting them needs the SECURITY DEFINER lookup-function pattern from migration 112 first.
# This set may only shrink. A new tenant-scoped table must get RLS instead of being added here.
DOCUMENTED_EXCEPTIONS = {
    "users",
    "refresh_tokens",
    "user_invitations",
    "oauth_grants",
    "personal_access_tokens",
    # Public, unauthenticated intake form; tenant_id is nullable (NULL = platform-level grievance), so a
    # plain tenant policy would hide or reject those rows. Needs its own policy design.
    "grievances",
}

_MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "proposed" / "118_rls_remaining_tenant_tables.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("proposed_rls_117", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_postgres_is_available_when_required():
    """In CI a missing PostgreSQL must fail loudly instead of skipping every check."""
    assert IS_POSTGRES, "REQUIRE_POSTGRES_TESTS=1 but DATABASE_URL is not a PostgreSQL URL"


@pytest.fixture(scope="module")
def proposed_rls():
    """Apply the proposed migration (and create the probe role) on the test database."""
    mig = _load_migration()
    with engine.begin() as conn:
        conn.execute(text(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PROBE_ROLE}') THEN
                    CREATE ROLE {PROBE_ROLE} NOLOGIN;
                END IF;
            END $$
        """))
        conn.execute(text(mig.UPGRADE_SQL))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {PROBE_ROLE}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {PROBE_ROLE}"))
    yield mig
    with engine.begin() as conn:
        conn.execute(text(mig.DOWNGRADE_SQL))


def test_proposed_migration_is_idempotent(proposed_rls):
    """Production builds tables with create_all, so every statement must tolerate re-running."""
    with engine.begin() as conn:
        conn.execute(text(proposed_rls.UPGRADE_SQL))
        conn.execute(text(proposed_rls.UPGRADE_SQL))


def test_every_tenant_scoped_table_has_rls_or_is_a_documented_exception(proposed_rls):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
              AND EXISTS (
                  SELECT 1 FROM information_schema.columns k
                  WHERE k.table_schema = 'public' AND k.table_name = c.relname AND k.column_name = 'tenant_id'
              )
            ORDER BY 1
        """)).all()
    without_rls = {r[0] for r in rows}
    unexpected = without_rls - DOCUMENTED_EXCEPTIONS
    assert not unexpected, (
        f"tenant-scoped tables without row-level security (add a policy, do not extend the exception list): "
        f"{sorted(unexpected)}"
    )


def test_policies_are_keyed_on_the_tenant_setting(proposed_rls):
    with engine.connect() as conn:
        rows = dict(conn.execute(text(
            "SELECT tablename, qual FROM pg_policies WHERE policyname = tablename || '_tenant_isolation'"
        )).all())
        present = [
            t for t in proposed_rls.TENANT_TABLES
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{t}"}).scalar() is not None
        ]
    assert present, "none of the proposed tables exist -- is the test database built?"
    for table in present:
        assert table in rows, f"{table} has no tenant_isolation policy"
        assert "app.tenant_id" in rows[table]


def _seed_two_tenants():
    """Two tenants, one guest and one identity signal each. Returns ((tenant_a, guest_a), (tenant_b, guest_b))."""
    from app.models.guest import Guest
    from app.models.guest_identity import GuestIdentity
    from app.models.tenant import Tenant

    session = TestingSessionLocal()
    try:
        made = []
        for label in ("a", "b"):
            tenant = Tenant(id=str(uuid.uuid4()), name=f"RLS {label}", slug=f"rls-{label}-{uuid.uuid4().hex[:6]}", plan="growth")
            session.add(tenant)
            session.flush()
            guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name=f"Guest {label}")
            session.add(guest)
            session.flush()
            session.add(GuestIdentity(
                id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
                identity_type="phone", identity_value=f"+9190000{uuid.uuid4().int % 100000:05d}", confidence=0.9,
            ))
            made.append((tenant.id, guest.id))
        session.commit()
        return made
    finally:
        session.close()


def _cleanup(pairs):
    with engine.begin() as conn:
        for tenant_id, guest_id in pairs:
            conn.execute(text("DELETE FROM guest_identities WHERE tenant_id = :t"), {"t": tenant_id})
            conn.execute(text("DELETE FROM guests WHERE id = :g"), {"g": guest_id})
            conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


def _count_as_probe(tenant_id):
    """guest_identities rows visible to the restricted role with the tenant context set (or not)."""
    with engine.begin() as conn:
        conn.execute(text(f"SET LOCAL ROLE {PROBE_ROLE}"))
        if tenant_id is not None:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
        return conn.execute(text("SELECT count(*) FROM guest_identities")).scalar()


def test_restricted_role_only_sees_its_own_tenants_rows(proposed_rls):
    (tenant_a, guest_a), (tenant_b, guest_b) = pairs = _seed_two_tenants()
    try:
        assert _count_as_probe(tenant_a) == 1, "tenant A must see exactly its own signal"
        assert _count_as_probe(tenant_b) == 1, "tenant B must see exactly its own signal"
        assert _count_as_probe(None) == 0, "no tenant context must see nothing, not everything"
        assert _count_as_probe("not-a-tenant") == 0
    finally:
        _cleanup(pairs)


def test_restricted_role_cannot_write_into_another_tenant(proposed_rls):
    (tenant_a, guest_a), (tenant_b, guest_b) = pairs = _seed_two_tenants()
    try:
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="row-level security"):
            with engine.begin() as conn:
                conn.execute(text(f"SET LOCAL ROLE {PROBE_ROLE}"))
                conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_a})
                conn.execute(text(
                    "INSERT INTO guest_identities (id, tenant_id, guest_id, identity_type, identity_value, confidence) "
                    "VALUES (:i, :t, :g, 'phone', '+919999900000', 0.9)"
                ), {"i": str(uuid.uuid4()), "t": tenant_b, "g": guest_b})
    finally:
        _cleanup(pairs)


def test_set_tenant_context_does_not_leak_past_the_transaction(proposed_rls):
    """The setting must be transaction-local: a pooled connection reused by the next request starts clean."""
    from app.core.database import set_tenant_context

    session = TestingSessionLocal()
    try:
        set_tenant_context(session, "tenant-123")
        assert session.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() == "tenant-123"
        session.commit()
        assert session.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() in (None, "")
    finally:
        session.close()


# ── Per-table matrix over every proposed table ───────────────────────────────────────────────────

ALL_PROPOSED_TABLES = [
    "guest_identities", "inquiry_quotes", "inquiry_stage_log", "automation_rules", "automation_runs",
    "insights", "saved_views", "blocked_dates", "property_addons", "seasonal_rates",
    "consent_log", "incidents", "instagram_insights_snapshots", "instagram_post_snapshots", "stays_date_quarantine",
    "meta_quality_snapshots",
]


def _literal_for(column):
    """A harmless SQL literal for a required column, chosen from its type (test data only)."""
    name, dtype, udt = column["column_name"], column["data_type"], column["udt_name"]
    if dtype in ("character varying", "text", "character"):
        width = column["character_maximum_length"] or 36
        return f"left(replace(gen_random_uuid()::text, '-', ''), {min(width, 32)})"
    if dtype in ("integer", "bigint", "smallint", "numeric", "double precision", "real"):
        return "0"
    if dtype == "boolean":
        return "false"
    if dtype.startswith("timestamp"):
        return "now()"
    if dtype == "date":
        return "current_date"
    if dtype in ("json", "jsonb"):
        return "'{}'::" + dtype
    if dtype == "ARRAY":
        return "'{}'"
    if dtype == "USER-DEFINED":
        return (
            "(SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            f"WHERE t.typname = '{udt}' ORDER BY enumsortorder LIMIT 1)::{udt}"
        )
    raise AssertionError(f"no test literal for {name} ({dtype})")


def _insert_sql(conn, table):
    """INSERT ... VALUES for a row with every NOT NULL, default-less column filled; tenant_id is a bind."""
    cols = conn.execute(text("""
        SELECT column_name, data_type, udt_name, is_nullable, column_default, character_maximum_length
        FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position
    """), {"t": table}).mappings().all()
    names, values = [], []
    for c in cols:
        if c["column_name"] == "tenant_id":
            names.append("tenant_id")
            values.append(":tenant")
        elif c["is_nullable"] == "NO" and c["column_default"] is None:
            names.append(c["column_name"])
            values.append(_literal_for(c))
    return f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({", ".join(values)})'


def _as_probe(conn, tenant_id):
    """Switch the open transaction to the restricted role with a tenant context.

    Foreign-key checks are skipped for the seeding/probing transaction (a superuser-only setting, applied
    BEFORE the role switch); row-level security does not depend on triggers, so it still applies."""
    conn.execute(text(f"SET LOCAL ROLE {PROBE_ROLE}"))
    if tenant_id is not None:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})


@pytest.mark.parametrize("table", ALL_PROPOSED_TABLES)
def test_table_isolates_read_insert_update_delete(proposed_rls, table):
    assert table in proposed_rls.TENANT_TABLES, "table list in the test drifted from the migration"
    _assert_table_isolates(table)


# Tables whose policy ships in their own migration (not in the proposed 118), read from the migration so the list can't drift.
def _migration_tables(filename):
    spec = importlib.util.spec_from_file_location(
        f"mig_{filename}", pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module._TABLES)


OPS_TABLES = _migration_tables("131_ops_foundations.py")


def test_ops_table_list_is_the_nine_planned_tables():
    assert sorted(OPS_TABLES) == sorted([
        "staff_profiles", "staff_duties", "shift_patterns", "shift_overrides", "escalation_chains",
        "ops_settings", "ops_items", "ops_escalation_events", "ops_alert_sends",
    ])


# One row per tenant (UNIQUE tenant_id): the "may insert for its own tenant" probe uses a fresh tenant instead of a second row.
ONE_ROW_PER_TENANT = {"ops_settings"}


@pytest.mark.parametrize("table", OPS_TABLES)
def test_ops_table_isolates_read_insert_update_delete(proposed_rls, table):
    _assert_table_isolates(table)


def _assert_table_isolates(table):
    a, b = f"rls-a-{uuid.uuid4().hex[:8]}", f"rls-b-{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar()
        assert exists is not None, f"{table} does not exist in the test database"
        insert = _insert_sql(conn, table)
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text(insert), {"tenant": a})
        conn.execute(text(insert), {"tenant": b})
        try:
            # read: each tenant sees exactly its own row; no context or an unknown tenant sees nothing
            for tenant, expected in ((a, 1), (b, 1), (None, 0), ("nobody", 0)):
                conn.execute(text("SAVEPOINT s"))
                _as_probe(conn, tenant)
                seen = conn.execute(
                    text(f'SELECT count(*) FROM "{table}" WHERE tenant_id IN (:a, :b)'), {"a": a, "b": b}
                ).scalar()
                conn.execute(text("ROLLBACK TO SAVEPOINT s"))
                assert seen == expected, f"{table}: tenant {tenant!r} saw {seen} rows, expected {expected}"

            # insert: same tenant allowed, other tenant denied
            own = f"rls-c-{uuid.uuid4().hex[:8]}" if table in ONE_ROW_PER_TENANT else a
            conn.execute(text("SAVEPOINT s"))
            _as_probe(conn, own)
            conn.execute(text(insert), {"tenant": own})
            conn.execute(text("ROLLBACK TO SAVEPOINT s"))
            conn.execute(text("SAVEPOINT s"))
            _as_probe(conn, a)
            with pytest.raises(Exception, match="row-level security"):
                conn.execute(text(insert), {"tenant": b})
            conn.execute(text("ROLLBACK TO SAVEPOINT s"))

            # update: only own rows change; moving a row to another tenant is rejected
            conn.execute(text("SAVEPOINT s"))
            _as_probe(conn, a)
            changed = conn.execute(
                text(f'UPDATE "{table}" SET tenant_id = tenant_id WHERE tenant_id IN (:a, :b)'), {"a": a, "b": b}
            ).rowcount
            conn.execute(text("ROLLBACK TO SAVEPOINT s"))
            assert changed == 1, f"{table}: UPDATE as tenant A touched {changed} rows"
            conn.execute(text("SAVEPOINT s"))
            _as_probe(conn, a)
            with pytest.raises(Exception, match="row-level security"):
                conn.execute(text(f'UPDATE "{table}" SET tenant_id = :b WHERE tenant_id = :a'), {"a": a, "b": b})
            conn.execute(text("ROLLBACK TO SAVEPOINT s"))

            # delete: only own rows go
            conn.execute(text("SAVEPOINT s"))
            _as_probe(conn, a)
            deleted = conn.execute(
                text(f'DELETE FROM "{table}" WHERE tenant_id IN (:a, :b)'), {"a": a, "b": b}
            ).rowcount
            conn.execute(text("ROLLBACK TO SAVEPOINT s"))
            assert deleted == 1, f"{table}: DELETE as tenant A removed {deleted} rows"
        finally:
            conn.execute(text("RESET ROLE"))
            conn.execute(text(f'DELETE FROM "{table}" WHERE tenant_id IN (:a, :b)'), {"a": a, "b": b})


# ── What bypasses row-level security (the facts the production checklist depends on) ─────────────

@pytest.fixture()
def scratch_table(proposed_rls):
    """A throwaway table with the same policy shape, owned by a non-superuser role, with a row per tenant."""
    owner, bypass = "haip_rls_owner", "haip_rls_bypass"
    with engine.begin() as conn:
        for role, extra in ((owner, ""), (bypass, " BYPASSRLS")):
            conn.execute(text(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{role}') "
                f"THEN CREATE ROLE {role} NOLOGIN{extra}; END IF; END $$"
            ))
        conn.execute(text("DROP TABLE IF EXISTS rls_scratch CASCADE"))
        conn.execute(text("CREATE TABLE rls_scratch (id text PRIMARY KEY, tenant_id text NOT NULL)"))
        conn.execute(text(f"ALTER TABLE rls_scratch OWNER TO {owner}"))
        conn.execute(text("ALTER TABLE rls_scratch ENABLE ROW LEVEL SECURITY"))
        conn.execute(text(
            "CREATE POLICY rls_scratch_tenant_isolation ON rls_scratch "
            "USING (tenant_id = current_setting('app.tenant_id', true)::text)"
        ))
        conn.execute(text("INSERT INTO rls_scratch VALUES ('1','a'), ('2','b')"))
        conn.execute(text(f"GRANT SELECT ON rls_scratch TO {PROBE_ROLE}, {bypass}"))
        conn.execute(text(
            "CREATE OR REPLACE FUNCTION rls_scratch_count() RETURNS bigint LANGUAGE sql SECURITY DEFINER "
            "AS $$ SELECT count(*) FROM rls_scratch $$"
        ))
        conn.execute(text(f"GRANT EXECUTE ON FUNCTION rls_scratch_count() TO {PROBE_ROLE}"))
    yield owner, bypass
    with engine.begin() as conn:
        conn.execute(text("DROP FUNCTION IF EXISTS rls_scratch_count()"))
        conn.execute(text("DROP TABLE IF EXISTS rls_scratch"))


def _count_scratch(role=None, tenant="a"):
    with engine.begin() as conn:
        if role:
            conn.execute(text(f"SET LOCAL ROLE {role}"))
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
        return conn.execute(text("SELECT count(*) FROM rls_scratch")).scalar()


def test_who_is_subject_to_a_tenant_policy(scratch_table):
    owner, bypass = scratch_table
    assert _count_scratch(PROBE_ROLE) == 1, "an ordinary role is restricted to its tenant"
    assert _count_scratch(None) == 2, "a SUPERUSER (the test connection) bypasses every policy"
    assert _count_scratch(bypass) == 2, "BYPASSRLS bypasses every policy"
    assert _count_scratch(owner) == 2, "the table OWNER bypasses a policy unless FORCE ROW LEVEL SECURITY is set"
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE rls_scratch FORCE ROW LEVEL SECURITY"))
    assert _count_scratch(owner) == 1, "FORCE subjects the owner to the policy"
    assert _count_scratch(None) == 2, "FORCE does not constrain a superuser"


def test_security_definer_function_sees_every_tenant(scratch_table):
    """A SECURITY DEFINER function runs as its owner, so it is not limited to the caller's tenant."""
    with engine.begin() as conn:
        conn.execute(text(f"SET LOCAL ROLE {PROBE_ROLE}"))
        conn.execute(text("SELECT set_config('app.tenant_id', 'a', true)"))
        assert conn.execute(text("SELECT rls_scratch_count()")).scalar() == 2


def test_applying_the_migration_keeps_existing_rows(proposed_rls):
    """Upgrade path: a table that already holds rows keeps all of them when RLS is enabled."""
    t = f"rls-upgrade-{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(text(proposed_rls.DOWNGRADE_SQL))
        insert = _insert_sql(conn, "blocked_dates")
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text(insert), {"tenant": t})
        before = conn.execute(text("SELECT count(*) FROM blocked_dates WHERE tenant_id = :t"), {"t": t}).scalar()
        conn.execute(text(proposed_rls.UPGRADE_SQL))
        after = conn.execute(text("SELECT count(*) FROM blocked_dates WHERE tenant_id = :t"), {"t": t}).scalar()
        rls_on = conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname = 'blocked_dates'")).scalar()
        conn.execute(text("DELETE FROM blocked_dates WHERE tenant_id = :t"), {"t": t})
    assert before == after == 1
    assert rls_on is True
