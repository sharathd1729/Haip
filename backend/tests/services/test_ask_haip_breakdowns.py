"""Ask HAIP split questions come from the dashboards' breakdowns (ask_haip_breakdowns), never from model-written SQL."""

import uuid

import pytest

from app.models.tenant import Tenant
from app.services import ask_haip_breakdowns as bd
from app.services import ask_haip_kpi
from app.services.ask_haip_freeform_service import answer_freeform_question
from tests.test_dashboard_tabs import _world

PERIOD = ask_haip_kpi.period("this month")


@pytest.mark.parametrize(
    "q,expected",
    [
        ("Which source brought the most bookings last month?", ("source", ["bookings"])),
        ("How many leads came from Instagram this month?", ("source", ["leads"])),
        ("Which property is busiest this month?", ("property", ["bookings"])),
        ("Revenue per villa last month", ("property", ["revenue"])),
        ("New leads by agent this month", ("owner", ["leads"])),
        ("What was our revenue each month this year?", ("month", ["revenue"])),
        ("How many leads this month?", None),
        ("Who called yesterday?", None),
    ],
)
def test_classify(q, expected):
    assert bd.classify(q) == expected


def test_source_split_orders_by_what_was_asked_and_puts_a_named_channel_first(db, monkeypatch):
    rows = [
        {"key": "whatsapp", "label": "WhatsApp", "leads": 9, "bookings": 1, "value": 20000.0},
        {"key": "instagram", "label": "Instagram", "leads": 4, "bookings": 3, "value": 90000.0},
    ]
    monkeypatch.setattr(bd.lead_metrics, "by_first_touch", lambda *a, **k: rows)
    out = bd.answer(db, "t1", "Which source brought the most bookings this month?", PERIOD)
    assert [r["source"] for r in out["rows"]] == [
        "Instagram",
        "WhatsApp",
    ] and "Top source by bookings: Instagram" in out["narrative"]
    out = bd.answer(db, "t1", "How many leads came from Instagram this month?", PERIOD)
    assert out["rows"][0]["source"] == "Instagram" and out["rows"][1]["source"] == "WhatsApp"
    assert out["rows"][0]["conversion"] == "75.0%" and out["source"] == "shared_metrics"


def test_property_split_uses_bookings_made_in_the_period_and_stays_in_the_workspace(db, tenant_and_user):
    t = tenant_and_user["tenant"]
    tid = t["id"] if isinstance(t, dict) else t.id
    _world(db, tid)
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _world(db, other.id)
    out = bd.answer(db, tid, "Which property is busiest this month?", PERIOD)
    assert out["rows"] == [{"property": "Cedar Cottage", "bookings_made": 4, "booked_value": "Rs 90,000"}]


@pytest.mark.asyncio
async def test_split_questions_never_reach_the_model(db, tenant_and_user, monkeypatch):
    t = tenant_and_user["tenant"]
    tid = t["id"] if isinstance(t, dict) else t.id

    def no_llm(task):
        raise AssertionError("a split question must not call the model")

    monkeypatch.setattr("app.services.ask_haip_freeform_service.get_llm", no_llm)
    out = await answer_freeform_question(
        db=db, tenant_id=tid, user_id="u1", question="Which source brought the most bookings last month?"
    )
    assert out["source"] == "shared_metrics" and out["metrics"] == ["breakdown.source"]
