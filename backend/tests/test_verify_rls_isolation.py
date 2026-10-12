"""The production isolation verifier (scripts/verify_rls_isolation.py) must stay read-only and in sync with migration 118."""
import importlib.util
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "verify_rls_isolation.py"
PROPOSED = BACKEND / "alembic" / "proposed" / "118_rls_remaining_tenant_tables.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_table_lists_match_migration_118_and_the_test_exceptions():
    script, proposed = _load(SCRIPT, "verify_script"), _load(PROPOSED, "proposed_118")
    from tests.test_rls_postgres import DOCUMENTED_EXCEPTIONS
    assert script.PROPOSED_118 == proposed.TENANT_TABLES, "update PROPOSED_118 in scripts/verify_rls_isolation.py"
    assert set(script.DOCUMENTED_EXCEPTIONS) == set(DOCUMENTED_EXCEPTIONS), "update DOCUMENTED_EXCEPTIONS in the script"


def test_the_verifier_only_reads():
    """Production safety: no statement it runs may write, lock for update or change schema, and it always rolls back."""
    source = SCRIPT.read_text(encoding="utf-8")
    statements = re.findall(r'text\(\s*f?"""?(.*?)"""?\s*[),]', source, flags=re.S) + re.findall(r'text\(\s*f?"([^"]*)"', source)
    assert statements, "no SQL found; the scan is broken"
    forbidden = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|VACUUM|LOCK\s+TABLE)\b|FOR\s+UPDATE", re.I)
    for sql in statements:
        assert not forbidden.search(sql), f"the verifier must not run: {sql.strip()[:80]}"
    assert "SET TRANSACTION READ ONLY" in source
    assert "conn.rollback()" in source
    assert "statement_timeout" in source
