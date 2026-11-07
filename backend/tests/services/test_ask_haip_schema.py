"""Ask HAIP's table descriptions must match the models: every real column, enum labels spelled exactly as stored
(Ratha, Nov 2026: the model wrote direction = 'outbound', the column stores 'OUTBOUND', answer "none" instead of 830),
and every value a hand-written note lists must be one the code really writes."""
import importlib.util
import re
from pathlib import Path

import sqlalchemy as sa

import app.models  # noqa: F401
from app.core.database import Base
from app.schemas.pipeline_stage import _VALID_CATEGORIES
from app.services import ai_mode_service, kpi_metrics, lead_types, message_author, work_queue_signals
from app.services.ask_haip_freeform_service import ALLOWED_TABLES, SQL_SYSTEM_PROMPT, describe_table
from app.services.ask_haip_kpi import families

# Values the code writes into plain text columns that a note lists (the model knows no enum for these).
WRITTEN_VALUES = {
    ("stays", "status"): {*kpi_metrics.OCCUPYING_STATUSES, "cancelled"},
    ("conversations", "ai_mode"): set(ai_mode_service.VALID_MODES),
    ("inquiries", "lead_type"): set(lead_types.LEAD_TYPES),
    ("pipeline_stages", "category"): set(_VALID_CATEGORIES),
    ("messages", "sender_kind"): {*message_author._AI_KINDS, *message_author._AUTOMATED_KINDS,
                                  *work_queue_signals.NOT_CONTACT_KINDS,
                                  "human", "campaign", "bridge_live", "bridge_history", "chat_export"},
}


def _described(table: str) -> dict[str, str]:
    return dict(part.split(" ", 1) for part in describe_table(table).split(", "))


def test_allowed_tables_match_the_analyst_role_grants():
    path = next(Path(__file__).resolve().parents[2].glob("alembic/versions/052_*.py"))
    spec = importlib.util.spec_from_file_location("m052", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(ALLOWED_TABLES) == set(module.ANALYST_READABLE_TABLES)


def test_every_model_column_and_enum_label_is_described():
    for table in ALLOWED_TABLES:
        columns = Base.metadata.tables[table].columns
        described = _described(table)
        assert list(described) == [c.name for c in columns], table
        for col in columns:
            if isinstance(col.type, sa.Enum):
                assert described[col.name] == "enum(" + "|".join(f"'{v}'" for v in col.type.enums) + ")", (table, col.name)
        assert f"- {table}: " in SQL_SYSTEM_PROMPT and describe_table(table) in SQL_SYSTEM_PROMPT


def test_the_bug_columns_are_there_with_stored_spelling():
    messages = _described("messages")
    assert messages["direction"] == "enum('INBOUND'|'OUTBOUND')"
    assert {"sender_name", "sender_kind", "sender_id"} <= set(messages)
    assert "disposition" not in _described("calls")  # the old hand list named a column that never existed


def test_note_columns_exist_and_listed_values_are_written_by_the_code():
    for table, note in ALLOWED_TABLES.items():
        columns = {c.name: c for c in Base.metadata.tables[table].columns}
        value_lists = re.findall(r"\b([a-z_]+) ([a-z0-9_]+(?:\|[a-z0-9_]+)+)", note)
        listed_values = {v for _, values in value_lists for v in values.split("|")}
        for word in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", note):
            assert word in columns or word in ALLOWED_TABLES or word in listed_values, (table, word)
        for column, values in value_lists:
            assert column in columns, (table, column)
            col_type = columns[column].type
            known = set(col_type.enums) if isinstance(col_type, sa.Enum) else WRITTEN_VALUES.get((table, column))
            assert known is not None, f"{table}.{column}: add its written values to WRITTEN_VALUES"
            assert set(values.split("|")) <= known, (table, column, set(values.split("|")) - known)


def test_kpi_questions_route_to_shared_metrics_and_others_do_not():
    assert families("How many leads did we get yesterday?") == ["leads"]
    assert families("What was revenue last month?") == ["revenue"]
    assert families("occupancy this month") == ["occupancy"]
    assert families("What is our SLA in the last 7 days?") == ["sla"]
    assert families("total bookings in the last 30 days") == ["bookings"]
    assert families("outbound messages in the last 30 days") == []
    assert families("how many inquiries per stage") == []  # a split stays on freeform SQL


async def test_kpi_question_answers_from_shared_metrics_for_this_tenant_only(db, monkeypatch):
    import uuid
    from datetime import datetime, timezone

    from app.models.ask_haip import AskHaipFreeformQuery
    from app.models.guest import Guest
    from app.models.tenant import Tenant
    from app.services import ask_haip_freeform_service as svc

    def tenant():
        t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(t)
        db.flush()
        return t

    mine, other = tenant(), tenant()
    now = datetime.now(timezone.utc)
    for t, n in ((mine, 2), (other, 5)):
        for _ in range(n):
            db.add(Guest(id=str(uuid.uuid4()), tenant_id=t.id, lead_identified_at=now))
    db.commit()
    monkeypatch.setattr(svc, "get_llm", lambda task: (_ for _ in ()).throw(AssertionError("no LLM for a KPI question")))

    result = await svc.answer_freeform_question(db=db, tenant_id=mine.id, user_id="u1",
                                                question="How many leads did we get today?")

    assert result["source"] == "shared_metrics" and result["sql"] is None
    assert {r["metric"]: r["value"] for r in result["rows"]}["leads.identified_new"] == 2
    audit = db.query(AskHaipFreeformQuery).filter_by(tenant_id=mine.id).one()
    assert audit.status == "ok" and audit.generated_sql.startswith("-- shared metrics: leads.identified_new")
