"""Read-only check of tenant isolation as seen by the database role the application really connects with.

Run it INSIDE the API container so it uses the application's own connection (no connection string, password or token
is typed, pasted or printed):

    docker compose -f docker-compose.prod.yml exec api python scripts/verify_rls_isolation.py

What it does, and what it does not:

  Part 1  CONFIGURATION   which role, its privileges, table ownership, RLS enabled/forced, policies, SECURITY DEFINER functions.
                          Reading these tells you what the database is *set up* to do.
  Part 2  BEHAVIOUR       for each table with RLS enabled, sets the tenant context to tenant X inside a read-only transaction
                          and counts how many rows of OTHER tenants are visible (must be 0), and how many rows are visible
                          with no context at all (must be 0). Counts only; no row content is read or printed.
                          This is what *proves* isolation for this role. It cannot prove isolation for a different role, for
                          tables without RLS (those rely on application filters), or for code paths that bypass the session.
  Part 3  COVERAGE        tenant-data tables that have no RLS and are neither in the proposed migration 118 nor a documented
                          exception.

Safety: every statement is a SELECT or SET LOCAL inside a transaction opened with SET TRANSACTION READ ONLY, which is
always rolled back. Nothing is written, no table is locked beyond ACCESS SHARE, and a statement timeout caps each query.
"""
import os
import sys

# `python scripts/foo.py` puts scripts/ on sys.path, not the project root; add the root like the other scripts do.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.core.database import engine  # noqa: E402

# Keep in sync with alembic/proposed/118_rls_remaining_tenant_tables.py and tests/test_rls_postgres.py
# (tests/test_verify_rls_isolation.py fails if they drift).
PROPOSED_118 = [
    "guest_identities", "inquiry_quotes", "inquiry_stage_log", "automation_rules", "automation_runs", "insights",
    "saved_views", "blocked_dates", "property_addons", "seasonal_rates", "consent_log", "incidents",
    "instagram_insights_snapshots", "instagram_post_snapshots", "stays_date_quarantine", "meta_quality_snapshots",
]
DOCUMENTED_EXCEPTIONS = ["users", "refresh_tokens", "user_invitations", "oauth_grants", "personal_access_tokens", "grievances"]


def main() -> int:
    if engine.dialect.name != "postgresql":
        print("Not PostgreSQL: nothing to verify.")
        return 2
    problems = 0
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = '10s'"))

        # ── Part 1: configuration ───────────────────────────────────────────────────────────────────────
        role = conn.execute(text(
            "SELECT r.rolname, r.rolsuper, r.rolbypassrls, r.rolinherit FROM pg_roles r WHERE r.rolname = current_user"
        )).one()
        print(f"\n== PART 1  CONFIGURATION (role names and flags only)\nconnected as: {role.rolname}  superuser={role.rolsuper}  bypassrls={role.rolbypassrls}")
        member_of = conn.execute(text(
            "SELECT r.rolname, r.rolsuper, r.rolbypassrls FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
            "WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = current_user)")).all()
        for m in member_of:
            print(f"  member of: {m.rolname}  superuser={m.rolsuper}  bypassrls={m.rolbypassrls}")
        role_bypasses = role.rolsuper or role.rolbypassrls or any(m.rolsuper or m.rolbypassrls for m in member_of)
        if role_bypasses:
            print("  >> THIS ROLE BYPASSES ROW-LEVEL SECURITY: policies do not constrain the application.")

        tables = conn.execute(text("""
            SELECT c.relname, c.relrowsecurity AS rls, c.relforcerowsecurity AS forced, pg_get_userbyid(c.relowner) AS owner,
                   (SELECT count(*) FROM pg_policies p WHERE p.schemaname='public' AND p.tablename=c.relname) AS policies,
                   COALESCE((SELECT n_live_tup FROM pg_stat_user_tables u WHERE u.relid = c.oid), 0) AS est_rows
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname='public' AND c.relkind='r'
              AND EXISTS (SELECT 1 FROM information_schema.columns k WHERE k.table_schema='public' AND k.table_name=c.relname AND k.column_name='tenant_id')
            ORDER BY c.relname""")).all()
        print(f"\ntenant-scoped tables: {len(tables)}")
        effective = []
        for t in tables:
            owns = t.owner == role.rolname
            applies = (not role_bypasses) and t.rls and ((not owns) or t.forced)
            tag = "RLS applies to this role" if applies else ("RLS on but NOT applied to this role" if t.rls else "no RLS")
            print(f"  {t.relname:34s} rls={str(t.rls):5s} forced={str(t.forced):5s} owner={t.owner:14s} policies={t.policies}  -> {tag}")
            if applies:
                effective.append((t.relname, t.est_rows))

        weak = conn.execute(text("""
            SELECT tablename, policyname, cmd, roles::text, (qual IS NULL) AS no_using, (with_check IS NULL) AS no_check
            FROM pg_policies WHERE schemaname='public' AND (qual IS NULL OR qual NOT LIKE '%app.tenant_id%')
            ORDER BY 1""")).all()
        print("\npolicies not keyed on app.tenant_id (review each):", weak or "none")
        defs = conn.execute(text(
            "SELECT p.proname, pg_get_userbyid(p.proowner) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.prosecdef ORDER BY 1")).all()
        print("SECURITY DEFINER functions (run as their owner, ignore the caller's tenant; expected: api_key_lookup, ical_feed_tenant):")
        for d in defs:
            print(f"  {d[0]}  runs as {d[1]}")

        # ── Part 2: behaviour ───────────────────────────────────────────────────────────────────────────
        print("\n== PART 2  BEHAVIOUR (counts only)")
        tenant_ids = [r[0] for r in conn.execute(text("SELECT id FROM tenants ORDER BY created_at LIMIT 3")).all()]
        if len(tenant_ids) < 2:
            print("  fewer than two tenants: cannot compare tenants.")
        for name, est_rows in effective:
            foreign_seen = 0
            for tid in tenant_ids:
                conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid})
                foreign_seen += conn.execute(text(f'SELECT count(*) FROM "{name}" WHERE tenant_id <> :t'), {"t": tid}).scalar()
            conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            no_context = conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar()
            ok = foreign_seen == 0 and no_context == 0
            problems += 0 if ok else 1
            note = "" if est_rows else "  (table looks empty: a pass here is not informative)"
            print(f"  {name:34s} other-tenant rows visible under a tenant context: {foreign_seen}   rows visible with no context: {no_context}   est. rows: {est_rows}   {'PASS' if ok else 'FAIL'}{note}")
        if not effective:
            print("  No table has RLS that applies to this role, so nothing here proves isolation: it rests on the application's tenant filters.")
            problems += 1

        # ── Part 3: coverage ────────────────────────────────────────────────────────────────────────────
        print("\n== PART 3  COVERAGE")
        no_rls = {t.relname for t in tables if not t.rls}
        print("tenant tables without RLS that migration 118 would cover:", sorted(no_rls & set(PROPOSED_118)) or "none")
        print("tenant tables without RLS that are documented exceptions:  ", sorted(no_rls & set(DOCUMENTED_EXCEPTIONS)) or "none")
        uncovered = sorted(no_rls - set(PROPOSED_118) - set(DOCUMENTED_EXCEPTIONS))
        print("tenant tables without RLS covered by NEITHER (needs a decision):", uncovered or "none")
        problems += len(uncovered)
        conn.rollback()

    print("\nRESULT:", "all checks passed for this role" if problems == 0 else f"{problems} item(s) need attention (see FAIL / NOT protected lines above)")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
