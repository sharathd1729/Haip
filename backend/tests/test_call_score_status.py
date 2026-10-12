"""calls.ai_score_status: every value the application writes must fit the column (register P-1).

judge() wrote "skipped_no_transcript" (21 characters) into a varchar(20). SQLite does not enforce the width, so
nothing failed in tests; PostgreSQL raised "value too long for type character varying(20)", which defeated the
October fix that stops call_recovery from re-dispatching transcript-less calls forever.

* the source scan runs everywhere and would have caught the bug on SQLite;
* the database checks are meaningful on PostgreSQL (the production engine) and skip elsewhere.
"""
import ast
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.models.call import Call, CallDirection
from app.models.tenant import Tenant
from tests.conftest import TestingSessionLocal, engine

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
NEEDS_POSTGRES = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="column widths are only enforced by PostgreSQL; SQLite ignores varchar(n)",
)


def _status_literals():
    """Every string literal the app assigns to ai_score_status, with where it is written."""
    found = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # call.ai_score_status = "x"   /   obj.ai_score_status = "x"
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "ai_score_status" \
                            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        found.append((node.value.value, f"{path.relative_to(APP)}:{node.lineno}"))
            # Call(ai_score_status="x")
            if isinstance(node, ast.keyword) and node.arg == "ai_score_status" \
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found.append((node.value.value, f"{path.relative_to(APP)}:{node.value.lineno}"))
    return found


def test_the_scan_finds_the_known_writers():
    values = {v for v, _ in _status_literals()}
    assert {"pending", "processing", "done", "failed", "skipped_no_transcript", "skipped_short_call"} <= values


def test_every_status_the_app_writes_fits_the_model_column():
    width = Call.ai_score_status.type.length
    too_long = sorted((value, where, len(value)) for value, where in _status_literals() if len(value) > width)
    assert not too_long, f"ai_score_status is varchar({width}) but these values are longer: {too_long}"


@NEEDS_POSTGRES
def test_the_database_column_is_wide_enough():
    """The migrated/created database, not just the model: migration 117 widens existing installs."""
    longest = max(len(v) for v, _ in _status_literals())
    with engine.connect() as conn:
        width = conn.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='calls' AND column_name='ai_score_status'"
        )).scalar()
    assert width is None or width >= longest, f"calls.ai_score_status is varchar({width}); the app writes {longest} characters"


@NEEDS_POSTGRES
def test_the_longest_status_persists_and_reads_back():
    """The exact failure from production, on a real connection (committed, then read by a second session)."""
    session = TestingSessionLocal()
    tenant_id = str(uuid.uuid4())
    call_id = str(uuid.uuid4())
    try:
        session.add(Tenant(id=tenant_id, name="P1", slug=f"p1-{uuid.uuid4().hex[:6]}", plan="growth"))
        session.flush()
        session.add(Call(
            id=call_id, tenant_id=tenant_id, ivr_provider="vobiz", ivr_call_id=f"p1-{uuid.uuid4().hex[:8]}",
            direction=CallDirection.INBOUND, from_number="+919800000001", to_number="+912200000000",
            started_at=datetime.now(timezone.utc).isoformat(), ai_score_status="skipped_no_transcript",
        ))
        session.commit()
        reader = TestingSessionLocal()
        try:
            assert reader.query(Call).get(call_id).ai_score_status == "skipped_no_transcript"
        finally:
            reader.close()
    finally:
        session.rollback()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM calls WHERE id = :i"), {"i": call_id})
            conn.execute(text("DELETE FROM tenants WHERE id = :i"), {"i": tenant_id})
        session.close()
