"""
Adversarial test suite for the Ask HAIP free-form analyst's SQL validator
-- this is the actual security boundary (alongside the haip_analyst_ro DB
role, which can't be exercised in this sqlite-backed test suite). Per the
build plan, "1 happy path + 1 tenant-isolation test" is not sufficient
for the riskiest data-access path in the app.
"""
import os
import uuid
import pytest

from app.services.ask_haip_freeform_service import (
    _validate_and_scope, _enrich_stage_labels, FreeformRejected, answer_freeform_question,
)
from app.models.tenant import Tenant
from app.models.pipeline_stage import PipelineStage
from app.models.ask_haip import AskHaipFreeformQuery

_IS_POSTGRES = "sqlite" not in os.environ.get("DATABASE_URL", "sqlite")


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


# ── Validator: happy paths ──────────────────────────────────────────────────

def test_valid_single_table_query_gets_tenant_scoped():
    sql = _validate_and_scope("SELECT stage, COUNT(*) c FROM inquiries GROUP BY stage LIMIT 20", "tenant-abc")
    assert "tenant_id = :tenant_id" in sql
    assert "FROM inquiries" in sql


def test_missing_limit_gets_one_injected():
    sql = _validate_and_scope("SELECT name, phone FROM guests", "tenant-abc")
    assert "LIMIT 500" in sql


def test_over_limit_gets_capped():
    sql = _validate_and_scope("SELECT * FROM guests LIMIT 100000", "tenant-abc")
    assert "LIMIT 500" in sql
    assert "100000" not in sql


def test_existing_where_clause_preserved_alongside_tenant_scope():
    sql = _validate_and_scope("SELECT * FROM calls WHERE duration_seconds > 60 LIMIT 10", "tenant-abc")
    assert "duration_seconds" in sql
    assert "tenant_id = :tenant_id" in sql


# ── Validator: adversarial rejections ───────────────────────────────────────

def test_rejects_non_select_statements():
    for sql in [
        "DELETE FROM inquiries",
        "UPDATE inquiries SET budget = 0",
        "DROP TABLE inquiries",
        "INSERT INTO inquiries (id) VALUES ('x')",
        "TRUNCATE inquiries",
    ]:
        with pytest.raises(FreeformRejected):
            _validate_and_scope(sql, "tenant-abc")


def test_rejects_joins_v1_single_table_only():
    with pytest.raises(FreeformRejected, match="join"):
        _validate_and_scope(
            "SELECT * FROM inquiries JOIN guests ON inquiries.guest_id = guests.id",
            "tenant-abc",
        )


def test_rejects_non_allowlisted_tables():
    for table in ("users", "integrations", "refresh_tokens", "consents", "audit_events"):
        with pytest.raises(FreeformRejected, match="not queryable"):
            _validate_and_scope(f"SELECT * FROM {table}", "tenant-abc")


def test_own_tenant_id_predicate_from_llm_is_not_trusted_and_gets_overridden():
    """Even if the LLM writes its own (possibly wrong/malicious) tenant_id
    filter, the server-injected bound-parameter predicate is what actually
    executes -- the LLM's literal is just inert dead weight in the WHERE
    clause once ANDed with the real one."""
    sql = _validate_and_scope(
        "SELECT * FROM inquiries WHERE tenant_id = 'some-other-tenant-entirely'",
        "tenant-abc",
    )
    assert "tenant_id = :tenant_id" in sql
    # The bound param always wins because execution passes {"tenant_id": "tenant-abc"}
    # as the actual parameter value -- the literal string in the SQL is never used.


def test_trailing_injected_statement_is_structurally_discarded():
    """A classic SQL-injection-via-semicolon attempt: sqlglot.parse_one only
    parses the first statement, and the executed SQL is a fresh AST render
    -- not a substring of the LLM's raw text -- so anything after the first
    statement can never reach the DB regardless of content."""
    sql = _validate_and_scope("SELECT * FROM inquiries; DROP TABLE inquiries;", "tenant-abc")
    assert "DROP" not in sql.upper()
    assert "inquiries" in sql


def test_rejects_unparseable_sql():
    with pytest.raises(FreeformRejected):
        _validate_and_scope("this is not sql at all !!!", "tenant-abc")


def test_rejects_multiple_tables_via_implicit_comma_join():
    with pytest.raises(FreeformRejected):
        _validate_and_scope("SELECT * FROM inquiries, guests", "tenant-abc")


# ── End-to-end: rejection still gets audited ────────────────────────────────

@pytest.mark.asyncio
async def test_rejected_question_writes_audit_row(db, monkeypatch):
    """A rejection must never silently vanish -- it's written to the audit
    table with status='rejected', same as CLAUDE.md requires for any
    permission-sensitive path."""
    tenant = _make_tenant(db)
    db.commit()

    class _FakeLLM:
        async def complete(self, **kwargs):
            return {"content": "DELETE FROM inquiries"}  # malicious/broken generation

    monkeypatch.setattr(
        "app.services.ask_haip_freeform_service.get_llm",
        lambda task: _FakeLLM(),
    )

    result = await answer_freeform_question(
        db=db, tenant_id=tenant.id, user_id="u1", question="delete everything",
    )
    assert result["error"] is not None
    assert result["rows"] == []

    audit = db.query(AskHaipFreeformQuery).filter_by(tenant_id=tenant.id).first()
    assert audit is not None
    assert audit.status == "rejected"
    assert audit.question == "delete everything"


@pytest.mark.skipif(not _IS_POSTGRES, reason="ANY(:ids) array binding is Postgres-only")
def test_enrich_stage_labels_adds_readable_name_without_clobbering_unknowns(db):
    """V1's single-table restriction means the LLM can't JOIN to
    pipeline_stages itself -- this is the server-side workaround. A known
    stage_id gets a stage_label added; an unrecognized one is left alone
    rather than guessed at."""
    from sqlalchemy import text

    tenant = _make_tenant(db)
    stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant.id, key="active", label="Active", order=0)
    db.add(stage)
    db.commit()

    conn = db.connection()
    conn.execute(text("SELECT set_config(:k, :v, true)"), {"k": "app.tenant_id", "v": tenant.id})

    rows = [
        {"stage_id": stage.id, "inquiry_count": 5},
        {"stage_id": "not-a-real-stage-id", "inquiry_count": 1},
    ]
    enriched = _enrich_stage_labels(conn, tenant.id, rows)

    assert enriched[0]["stage_label"] == "Active"
    assert "stage_label" not in enriched[1]


def test_enrich_stage_labels_noop_when_no_stage_id_column(db):
    rows = [{"guest_name": "Vishwas", "total_spend": 15000}]
    result = _enrich_stage_labels(None, "tenant-abc", rows)
    assert result == rows


@pytest.mark.asyncio
async def test_fails_closed_when_ro_database_not_configured(db, monkeypatch):
    """Until an operator manually sets ANALYST_RO_DATABASE_URL (see migration
    052's docstring), a syntactically-valid, fully-scoped query must still
    be refused rather than silently falling back to a privileged
    connection."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "ANALYST_RO_DATABASE_URL", "")
    import app.services.ask_haip_freeform_service as svc
    monkeypatch.setattr(svc, "_ro_engine", None)

    tenant = _make_tenant(db)
    db.commit()

    class _FakeLLM:
        async def complete(self, **kwargs):
            return {"content": "SELECT stage, COUNT(*) c FROM inquiries GROUP BY stage LIMIT 20"}

    monkeypatch.setattr(svc, "get_llm", lambda task: _FakeLLM())

    result = await answer_freeform_question(
        db=db, tenant_id=tenant.id, user_id="u1", question="how many inquiries per stage",
    )
    assert result["rows"] == []
    assert result["error"] is not None

    audit = db.query(AskHaipFreeformQuery).filter_by(tenant_id=tenant.id).first()
    assert audit.status == "rejected"
