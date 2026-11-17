"""Create (or update) the restricted database role the API can connect as, so row-level security actually applies.

Workspace redesign Phase 0. Today the app connects as the table owner / a BYPASSRLS role (Supabase's ``postgres``), so
every RLS policy is defence in depth only. A role made here is NOSUPERUSER NOBYPASSRLS, owns nothing, and can only read
and write rows (no DDL), so every tenant policy binds it.

Dry run by default: prints the SQL (password redacted) and changes nothing.

    python scripts/create_app_db_role.py                       # print the plan
    ADMIN_DATABASE_URL=postgresql://owner:...@host/db \\
    APP_DB_PASSWORD=... python scripts/create_app_db_role.py --apply [--role haip_app] [--reset-password]

ADMIN_DATABASE_URL must be the owner (or a superuser) of the tables. The password comes only from APP_DB_PASSWORD
(never an argument, never printed).

Before pointing the API's DATABASE_URL at this role (docs/HAIP_Phase0_Production_Checklist.md):
  1. Run ``scripts/verify_rls_isolation.py`` connected AS this role; every table must PASS.
  2. Audit work that runs with no tenant context (Celery fan-outs across tenants, webhook lookups before the tenant is
     known): under a non-owner role those queries see NO rows on tables with a tenant policy.
  3. Keep migrations and startup ``create_all`` on the owner URL: this role cannot create or alter tables.
"""

from __future__ import annotations

import argparse
import os
import sys

GRANTS = [
    "GRANT CONNECT ON DATABASE {db} TO {role}",
    "GRANT USAGE ON SCHEMA public TO {role}",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
    "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {role}",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO {role}",
]
ATTRS = "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT LOGIN"


def plan(role: str, db: str, exists: bool, reset_password: bool) -> list[str]:
    """The statements, with the password as a placeholder (filled in only when applying)."""
    if not role.replace("_", "").isalnum() or not role[0].isalpha():
        raise SystemExit(f"Role name must be letters, digits and _: {role!r}")
    out = []
    if not exists:
        out.append(f"CREATE ROLE {role} {ATTRS} PASSWORD <APP_DB_PASSWORD>")
    else:
        out.append(f"ALTER ROLE {role} {ATTRS}" + (" PASSWORD <APP_DB_PASSWORD>" if reset_password else ""))
    out += [g.format(role=role, db=db) for g in GRANTS]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--role", default="haip_app")
    ap.add_argument("--apply", action="store_true", help="run it (needs ADMIN_DATABASE_URL and APP_DB_PASSWORD)")
    ap.add_argument("--reset-password", action="store_true", help="also set the password of an existing role")
    args = ap.parse_args(argv)

    url = os.environ.get("ADMIN_DATABASE_URL", "")
    if not args.apply:
        for stmt in plan(args.role, "<database>", exists=False, reset_password=False):
            print(stmt + ";")
        print("\nDry run: nothing changed. Add --apply with ADMIN_DATABASE_URL and APP_DB_PASSWORD set to run it.")
        return 0
    password = os.environ.get("APP_DB_PASSWORD", "")
    if not url.startswith("postgresql"):
        print("ADMIN_DATABASE_URL must be a postgresql:// URL of the table owner.", file=sys.stderr)
        return 2
    if len(password) < 16:
        print("APP_DB_PASSWORD must be set and at least 16 characters.", file=sys.stderr)
        return 2

    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(url.replace("postgresql+psycopg2://", "postgresql://"))
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT current_database(), EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (args.role,))
            db, exists = cur.fetchone()
            plan(args.role, db, exists, args.reset_password)  # validates the role name
            ident = {"role": sql.Identifier(args.role), "db": sql.Identifier(db)}
            head = ("CREATE ROLE {role} " if not exists else "ALTER ROLE {role} ") + ATTRS
            if not exists or args.reset_password:
                cur.execute(sql.SQL(head + " PASSWORD {pw}").format(pw=sql.Literal(password), **ident))
            else:
                cur.execute(sql.SQL(head).format(**ident))
            print(head.format(role=args.role) + (" PASSWORD ***" if not exists or args.reset_password else ""))
            for g in GRANTS:
                cur.execute(sql.SQL(g).format(**ident))
                print(g.format(role=args.role, db=db))
            cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", (args.role,))
            print("role ready: superuser={} bypassrls={}".format(*cur.fetchone()))
    finally:
        conn.close()
    print("Next: run scripts/verify_rls_isolation.py connected as this role before switching DATABASE_URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
