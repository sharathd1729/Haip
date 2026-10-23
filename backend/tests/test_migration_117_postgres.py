"""Migration 117 (widen calls.ai_score_status) and the rule that migration 118 stays out of the auto-applied directory.

The API container runs ``alembic upgrade head`` on start, so whatever is in ``alembic/versions`` is applied by the next
deploy. These tests run the migration's own ``upgrade()``/``downgrade()`` against a real PostgreSQL and check what a
release needs to know: only the intended column changes, rows are kept, re-running is harmless, a blocked ALTER fails
fast instead of freezing ``calls``, and the downgrade only moves the version marker.

PostgreSQL-only tests skip on SQLite; CI sets REQUIRE_POSTGRES_TESTS=1 so a missing PostgreSQL is a failure.
"""
import importlib.util
import os
import pathlib
import threading
import time
import uuid

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.models.call import Call
from tests.conftest import engine

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "117_widen_ai_score_status.py"
IS_POSTGRES = engine.dialect.name == "postgresql"
needs_postgres = pytest.mark.skipif(
    not IS_POSTGRES and os.environ.get("REQUIRE_POSTGRES_TESTS") != "1",
    reason="needs PostgreSQL (varchar widths and ALTER locking). Runs in CI.",
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_117", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(fn_name, conn):
    mod = _load()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mod, fn_name)()


def _width():
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='calls' AND column_name='ai_score_status'"
        )).scalar()


@pytest.fixture()
def narrow_column():
    """Put the column back to the pre-117 width for the test, and restore the migrated width afterwards."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE calls ALTER COLUMN ai_score_status TYPE VARCHAR(20)"))
    yield
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE calls ALTER COLUMN ai_score_status TYPE VARCHAR(40)"))


# ── runs on every database ────────────────────────────────────────────────────────────────────

def test_alembic_head_is_117_and_118_is_not_auto_applied():
    """Alembic only sees alembic/versions. 118 lives in alembic/proposed, so it cannot ship by accident.

    (Name kept because the failure register refers to it.) The chain tip is now 172 (analyst_reports + agent_experiments/assignments/lessons: the AI analyst and its learning loop; 171 is reserved for feat/lead-evidence-outcomes), on 170 (merge of 168 and 169), on 168 (agent_consults: Ask a manager) and 169 (inquiries.lead_type + the human validation review), both on 167 (creators, creator deals, OTA copy, review consent), on 166 (inquiries.heard_about), on 165 (ad drafts, boost rules, CAPI events), on 164 (critic scores + clip length), on 163 (marketing newsletters), on 162 (marketing channels + guest reviews), on 161 (marketing creative jobs), on 160 (media asset tags), on 159 (marketing brand reviews), on 158 (website builder: sites, versions, domains, booking holds), on 157 (Marketing Studio
    publish attempts), on 156 (marketing research), on 155 (marketing agency
    foundations), on 154 (Marketing Studio image jobs), on 153 (Marketing Studio tables; written as 129-133 on the
    unmerged branch and renumbered when it merged), on 152 (tasks.kind/playbook_run_id), on 151 (lead workflows: journeys, views, playbook runs/actions), on 150 (new booking: stays.gst_percent), on 148 (rate calculator: inquiry_quotes shared/approved
    columns; 147 is reserved by another branch), after 145 (public lead intake + ROI benchmarks),
    after 146 (impact baselines + profiles), after 144 (lead autopilot + calls.ai_insights), after 143 (knowledge source
    dates + flags), after 142 (sales_actions, the AI sales agent), after 141 (invoices + payment idempotency + quote-owned
    payment links), after 140 (quote options + quote capabilities; 129-139 are taken by unmerged branches), after 128
    (ical_event_bookings.locked repair), after 127 (merge of the 122-125 chain with 126, the organic_call source), after 125 (quote snapshot), 124 (business records), 123 (knowledge index health), 122 (lead identification), 121 (iCal event bookings) and 120 (iCal vehicle rules), which follows 119, the front-of-house data
    migration; 119 follows 117 directly because number 118 is reserved for the proposed RLS migration.
    """
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["172"]
    assert script.get_revision("172").down_revision == "170"
    assert set(script.get_revision("170").down_revision) == {"168", "169"}
    assert script.get_revision("168").down_revision == "167"
    assert script.get_revision("169").down_revision == "167"
    assert script.get_revision("167").down_revision == "166"
    assert script.get_revision("166").down_revision == "165"
    assert script.get_revision("165").down_revision == "164"
    assert script.get_revision("164").down_revision == "163"
    assert script.get_revision("163").down_revision == "162"
    assert script.get_revision("162").down_revision == "161"
    assert script.get_revision("161").down_revision == "160"
    assert script.get_revision("160").down_revision == "159"
    assert script.get_revision("159").down_revision == "158"
    assert script.get_revision("158").down_revision == "157"
    assert script.get_revision("157").down_revision == "156"
    assert script.get_revision("156").down_revision == "155"
    assert script.get_revision("155").down_revision == "154"
    assert script.get_revision("154").down_revision == "153"
    assert script.get_revision("153").down_revision == "152"
    assert script.get_revision("152").down_revision == "151"
    assert script.get_revision("151").down_revision == "150"
    assert script.get_revision("150").down_revision == "148"
    assert script.get_revision("148").down_revision == "145"
    assert script.get_revision("145").down_revision == "146"
    assert script.get_revision("146").down_revision == "144"
    assert script.get_revision("144").down_revision == "143"
    assert script.get_revision("143").down_revision == "142"
    assert script.get_revision("142").down_revision == "141"
    assert script.get_revision("141").down_revision == "140"
    assert script.get_revision("140").down_revision == "128"
    assert script.get_revision("128").down_revision == "127"
    assert script.get_revision("127").down_revision == ("125", "126")
    assert script.get_revision("126").down_revision == "121"
    assert script.get_revision("125").down_revision == "124"
    assert script.get_revision("123").down_revision == "122"
    assert script.get_revision("122").down_revision == "121"
    assert script.get_revision("121").down_revision == "120"
    assert script.get_revision("120").down_revision == "119"
    assert script.get_revision("119").down_revision == "117"
    assert script.get_revision("117").down_revision == "116"
    assert not list((BACKEND / "alembic" / "versions").glob("118*")), "118 must stay in alembic/proposed until approved"
    assert (BACKEND / "alembic" / "proposed" / "118_rls_remaining_tenant_tables.py").exists()


def test_the_migration_touches_only_the_intended_column():
    """Static check of the SQL the migration executes (not its docstring): one ALTER, on the one column."""
    import ast
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    upgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    sql = " ".join(n.value for n in ast.walk(upgrade) if isinstance(n, ast.Constant) and isinstance(n.value, str)).upper()
    assert sql.count("ALTER TABLE") == 1
    assert "ALTER TABLE CALLS ALTER COLUMN AI_SCORE_STATUS TYPE VARCHAR(40)" in " ".join(sql.split())
    for forbidden in ("DROP ", "DELETE ", "UPDATE ", "TRUNCATE", "RENAME", "CREATE "):
        assert forbidden not in sql, f"unexpected {forbidden.strip()} in migration 117"


# ── PostgreSQL ────────────────────────────────────────────────────────────────────────────────

@needs_postgres
def test_model_metadata_matches_the_migrated_schema():
    assert Call.ai_score_status.type.length == 40
    assert _width() == Call.ai_score_status.type.length


@needs_postgres
def test_upgrade_widens_only_this_column_and_keeps_rows(narrow_column):
    ids = [f"m117-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    with engine.begin() as conn:
        tenant = f"m117-t-{uuid.uuid4().hex[:6]}"
        conn.execute(text("SET LOCAL session_replication_role = replica"))   # synthetic rows without parent tenants
        for i, status in zip(ids, ("pending", "failed", "skipped_short_call")):
            conn.execute(text(
                "INSERT INTO calls (id, tenant_id, ivr_provider, ivr_call_id, direction, from_number, to_number, "
                "ai_score_status, created_at, updated_at) VALUES (:i, :t, 'vobiz', :c, 'INBOUND', '+91', '+91', :s, now(), now())"
            ), {"i": i, "t": tenant, "c": i, "s": status})
        before_cols = conn.execute(text(
            "SELECT column_name, character_maximum_length FROM information_schema.columns "
            "WHERE table_name='calls' AND column_name <> 'ai_score_status' ORDER BY column_name")).all()
    try:
        assert _width() == 20
        with engine.begin() as conn:
            _run("upgrade", conn)
        assert _width() == 40
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, ai_score_status FROM calls WHERE id = ANY(:ids) ORDER BY id"), {"ids": ids}).all()
            after_cols = conn.execute(text(
                "SELECT column_name, character_maximum_length FROM information_schema.columns "
                "WHERE table_name='calls' AND column_name <> 'ai_score_status' ORDER BY column_name")).all()
        assert sorted(r[1] for r in rows) == sorted(("pending", "failed", "skipped_short_call")), "existing rows must be preserved"
        assert before_cols == after_cols, "no other column of calls may change"
        with engine.begin() as conn:      # and the longest value the app writes now fits
            conn.execute(text("UPDATE calls SET ai_score_status = 'skipped_no_transcript' WHERE id = :i"), {"i": ids[0]})
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM calls WHERE id = ANY(:ids)"), {"ids": ids})


@needs_postgres
def test_upgrade_is_idempotent_and_never_narrows(narrow_column):
    with engine.begin() as conn:
        _run("upgrade", conn)
    with engine.begin() as conn:
        _run("upgrade", conn)                       # second run: no-op
    assert _width() == 40
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE calls ALTER COLUMN ai_score_status TYPE VARCHAR(100)"))
    with engine.begin() as conn:
        _run("upgrade", conn)                       # an already wider column must be left alone
    assert _width() == 100


@needs_postgres
def test_downgrade_only_moves_the_marker_and_leaves_the_wide_column(narrow_column):
    with engine.begin() as conn:
        _run("upgrade", conn)
        _run("downgrade", conn)
    assert _width() == 40, "downgrade must never narrow the column"


@needs_postgres
def test_a_blocked_alter_fails_fast_instead_of_freezing_calls(narrow_column):
    """A long transaction on calls must make the migration fail (and retry on restart), not queue an ACCESS EXCLUSIVE
    request that stalls every other query on the table."""
    mod = _load()
    mod.LOCK_TIMEOUT = "300ms"            # keep the test fast; production uses the module default (10 s)

    holder_ready, release = threading.Event(), threading.Event()

    def hold():                                     # a long-running transaction that has read from calls
        with engine.connect() as conn:
            trans = conn.begin()
            conn.execute(text("SELECT count(*) FROM calls"))
            holder_ready.set()
            release.wait(timeout=30)
            trans.rollback()

    t = threading.Thread(target=hold)
    t.start()
    assert holder_ready.wait(timeout=10)
    try:
        started = time.monotonic()
        with pytest.raises(Exception, match="lock timeout|canceling statement"):
            with engine.begin() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    mod.upgrade()
        assert time.monotonic() - started < 5, "the blocked ALTER must give up quickly"
        assert _width() == 20, "a failed migration must change nothing"
    finally:
        release.set()
        t.join(timeout=10)

    with engine.begin() as conn:                    # once the blocker is gone the retry succeeds
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
    assert _width() == 40
