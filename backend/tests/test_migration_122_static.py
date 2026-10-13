"""Migration 122 (lead identification) is additive, idempotent and tenant-safe -- checked from its source.

It uses PostgreSQL-only DDL (ADD COLUMN IF NOT EXISTS, row-level security), so it cannot be executed on the SQLite test database;
the PostgreSQL job in CI applies it for real (`alembic upgrade head`). These checks pin the properties that matter for a release:
nothing is dropped or rewritten on upgrade, every statement can be repeated, the new table has RLS with a tenant policy, the chain is
linear, and the data backfill cannot undo the schema change.
"""
import importlib.util
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PATH = BACKEND / "alembic" / "versions" / "122_lead_identification.py"


def _module():
    spec = importlib.util.spec_from_file_location("mig122", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _upgrade_source() -> str:
    src = PATH.read_text(encoding="utf-8")
    return src[src.index("def upgrade()"):src.index("def downgrade()")]


def test_the_chain_is_linear_and_follows_121():
    mod = _module()
    assert (mod.revision, mod.down_revision) == ("122", "121")


def test_upgrade_only_adds_and_every_statement_can_be_repeated():
    up = _upgrade_source()
    assert not re.search(r"\bDROP\b|\bDELETE\b|\bTRUNCATE\b|\bUPDATE\b(?! guests)", up.replace("lead_backfill", ""))
    assert up.count("ADD COLUMN IF NOT EXISTS") == 1                      # in a loop over the four columns
    for name in ("lead_identified_at", "lead_identified_via", "first_touch_channel", "first_touch_at"):
        assert name in up
    assert "CREATE TABLE IF NOT EXISTS" in up and up.count("CREATE INDEX IF NOT EXISTS") >= 3
    columns = re.search(r"for col, kind in \((.*?)\):", up, re.S).group(1)
    assert "NOT NULL" not in columns and "DEFAULT" not in columns         # nullable, no default: metadata-only on PostgreSQL


def test_the_new_table_has_row_level_security_and_a_guarded_tenant_policy():
    up = _upgrade_source()
    assert "ENABLE ROW LEVEL SECURITY" in up and "FORCE ROW LEVEL SECURITY" in up
    assert "NOT EXISTS" in up and "pg_policies" in up                      # the policy is only created once
    assert "current_setting('app.tenant_id', true)" in up
    assert "tenant_id             VARCHAR NOT NULL" in up


def test_a_failed_backfill_cannot_undo_the_schema_change_and_is_loud():
    up = _upgrade_source()
    assert "begin_nested()" in up and "except Exception" in up and "log.error" in up
    assert "lock_timeout" in up                                            # never queues behind a long transaction


def test_downgrade_reverses_only_what_upgrade_added():
    src = PATH.read_text(encoding="utf-8")
    down = src[src.index("def downgrade()"):]
    assert "DROP TABLE IF EXISTS" in down and "DROP COLUMN IF EXISTS" in down
    assert "guests" in down and "stays" not in down and "inquiries" not in down
