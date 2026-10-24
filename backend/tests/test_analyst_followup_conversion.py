"""Analyst "Ask a follow-up": the production failure (TimeoutError at 60 s on a route with no fallback) and its fix (own route
with Gemini fallback, one retry on a provider error / unusable answer, the failure reason stored), the trimmed facts the model
reads, and the code-computed conversion block (fixture numbers, tenant isolation, on demand for older reports)."""
import asyncio
import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from app.models.ask_haip import AskHaipFreeformQuery
from app.models.inquiry_360 import InquiryQuote
from app.models.lead_workflow import LeadJourney
from app.models.pipeline_stage import PipelineStage
from app.services.analyst import ask, conversion, reports
from app.services.analyst.periods import windows
from app.services.date_presets import IST
from tests.analyst_world import world, yesterday_at


def _audit_table(db):
    AskHaipFreeformQuery.__table__.create(bind=db.get_bind(), checkfirst=True)     # migration 052's table (not in create_all)


def _stage(db, w, key, label, category, won=False, lost=False):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=w.t.id, key=key, label=label, category=category,
                      is_closed_won=won, is_closed_lost=lost)
    db.add(s)
    db.flush()
    return s


def _seed_funnel(db, w):
    """4 enquiries yesterday: 0 booked (Sold, reason confirmed), 1 open + contacted in 10 min + quoted at 30 min (no follow-up),
    2 open in an invalid stage nobody contacted, 3 lost with only an AI-proposed reason."""
    sold, active = _stage(db, w, "sold", "Sold", "valid", won=True), _stage(db, w, "active", "Active", "valid")
    general, lost = _stage(db, w, "general_enquiry", "General Enquiry", "invalid"), _stage(db, w, "lost", "Lost", "valid", lost=True)
    at = yesterday_at(11)
    for inq, st in zip(w.inqs, (sold, active, general, lost)):
        inq.stage_id, inq.current_stage_entered_at = st.id, at + timedelta(hours=2)
    w.inqs[0].outcome_reason, w.inqs[0].outcome_reason_source = "package_fit", "person"
    w.inqs[3].outcome_proposal = {"status": "ready", "kind": "lost", "reason": "price"}
    db.add(LeadJourney(tenant_id=w.t.id, inquiry_id=w.inqs[1].id, guest_id=w.inqs[1].guest_id, received_at=at,
                       first_human_contact_at=at + timedelta(minutes=10), proposal_shared_at=at + timedelta(minutes=30)))
    db.add(InquiryQuote(tenant_id=w.t.id, inquiry_id=w.inqs[1].id, amount=50000, is_active=True, created_at=at))
    db.commit()


def _conv(db, w):
    cur = windows("daily_pulse", datetime.now(IST).date())[0]
    lo, hi = cur.bounds()
    return conversion.build(db, w.t, cur.d_from, cur.d_to, lo, hi)


def test_conversion_block_on_fixture_data_and_tenant_isolation(db):
    w = world(db, contacts=5, leads=4)
    _seed_funnel(db, w)
    c = _conv(db, w)
    steps = {s["step"]: s for s in c["funnel"]}
    assert [steps[k]["count"] for k in conversion.STEPS] == [4, 4, 3, 1, 1, 1]
    assert steps["qualified"]["rate_from_previous"] == 0.75 and steps["contacted"]["rate_from_previous"] == 0.3333
    assert steps["enquiries"]["rate_from_previous"] is None
    assert c["leaks"]["open_enquiries"] == 2 and c["leaks"]["open_no_contact_from_us"] == 1
    assert c["leaks"]["open_quoted_no_followup"] == 1 and c["leaks"]["open_contacted_never_quoted"] == 0
    assert {r["stage"] for r in c["leaks"]["open_by_stage"]} == {"Active", "General Enquiry"}
    assert c["speed"]["median_first_contact_minutes"] == 10 and c["speed"]["median_first_quote_minutes"] == 30
    assert c["speed"]["contacted_within_sla"] == 1 and c["speed"]["sla_minutes"] == 15
    assert c["reasons"]["lost"]["top"] == [{"reason": "Price", "confirmed": 0, "ai_proposed": 1}]
    assert c["reasons"]["won"]["top"] == [{"reason": "The package fit", "confirmed": 1, "ai_proposed": 0}]
    assert c["open_quotes"] == {"enquiries": 1, "latest_quote_total_estimate": 50000.0}
    assert "people_waiting" in c["waiting_now"]
    # another workspace sees none of it
    other = world(db, contacts=1, leads=0)
    o = _conv(db, other)
    assert all(s["count"] == 0 for s in o["funnel"]) and o["open_quotes"]["enquiries"] == 0
    assert o["reasons"]["lost"]["closed"] == 0


def test_new_reports_carry_conversion_and_the_model_gets_a_trimmed_copy(db):
    w = world(db)
    with patch("app.adapters.llm.get_llm", side_effect=RuntimeError("off")):
        r = reports.generate(db, w.t, "daily_pulse")
    assert r.facts["conversion"]["funnel"][0] == {"step": "enquiries", "count": 2, "rate_from_previous": None}
    slim = json.dumps(ask.for_model(r.facts), default=str)
    assert "conversion" in slim and '"evidence"' not in slim and '"hour"' not in slim and '"interval"' not in slim
    assert len(slim) < len(json.dumps(r.facts, default=str))


class _Seq:
    """An LLM adapter that plays a script: an exception to raise, a number of seconds to hang, or reply content."""
    provider = "scripted"

    def __init__(self, *steps):
        self.steps, self.calls = list(steps), []

    async def complete(self, **kw):
        self.calls.append(kw)
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        if isinstance(step, (int, float)):
            await asyncio.sleep(step)
        return {"content": step if isinstance(step, str) else json.dumps({"answer": "late"})}


def _ask(db, w, r, q, llm):
    item = ask.queue(db, r, w.mgr.id, q)
    db.commit()
    with patch("app.adapters.llm.get_llm", lambda *a, **k: llm):
        ask.answer(db, r, item["id"])
    return next(f for f in r.followups if f["id"] == item["id"])


def _report(db, w):
    with patch("app.adapters.llm.get_llm", side_effect=RuntimeError("off")):
        return reports.generate(db, w.t, "daily_pulse")


def test_timeout_is_stored_as_the_reason_and_audited(db):
    """The production failure: the model hangs past the bound -> failed, reason ``timeout`` (shown as such), no second try."""
    _audit_table(db)
    w = world(db)
    r = _report(db, w)
    llm = _Seq(5)
    with patch.object(ask, "TIMEOUT_S", 0.05):
        got = _ask(db, w, r, "Why are leads not converting?", llm)
    assert got["status"] == "failed" and got["reason"] == "timeout" and len(llm.calls) == 1
    row = db.query(AskHaipFreeformQuery).filter_by(tenant_id=w.t.id).one()
    assert row.status == "error" and row.reject_reason.startswith("timeout")


def test_slow_nvidia_falls_back_to_gemini_and_answers(db, monkeypatch):
    """Same hang on the primary, through the REAL router: the analyst_followup route falls back to Gemini and the question is
    answered (before the fix the route had no fallback and failed)."""
    from app.adapters import llm as router
    from app.core.config import settings
    _audit_table(db)
    w = world(db)
    r = _report(db, w)
    slow, gemini = _Seq(5), _Seq(json.dumps({"answer": "2 new leads came in."}))
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setitem(router._GEMINI_FALLBACK_TASKS, "analyst_followup", 0.05)
    monkeypatch.setattr(router, "_build_adapter", lambda provider, model=None: gemini if provider == "gemini" else slow)
    item = ask.queue(db, r, w.mgr.id, "How many leads?")
    db.commit()
    ask.answer(db, r, item["id"])
    got = next(f for f in r.followups if f["id"] == item["id"])
    assert got["status"] == "answered" and got["answer"] == "2 new leads came in." and got["reason"] is None
    assert len(slow.calls) == 1 and len(gemini.calls) == 1


def test_provider_error_is_retried_once_and_bad_output_is_reported(db):
    _audit_table(db)
    w = world(db)
    r = _report(db, w)
    flaky = _Seq(RuntimeError("502"), json.dumps({"answer": "2 new leads."}))
    got = _ask(db, w, r, "How many leads?", flaky)
    assert got["status"] == "answered" and got["attempts"] == 2
    empty = _Seq("")
    got = _ask(db, w, r, "How many leads?", empty)
    assert got["status"] == "failed" and got["reason"] == "bad_output" and len(empty.calls) == 2
    down = _Seq(RuntimeError("down"))
    assert _ask(db, w, r, "How many leads?", down)["reason"] == "provider_error"


def test_why_question_on_an_older_report_uses_conversion_computed_on_demand(db):
    """A report written before the conversion block existed: the follow-up computes it, the model reads it, and an answer
    citing its numbers survives the number check while an invented number is dropped."""
    _audit_table(db)
    w = world(db, contacts=5, leads=4)
    _seed_funnel(db, w)
    r = _report(db, w)
    old = dict(r.facts)
    old.pop("conversion")
    r.facts = old
    db.commit()
    llm = _Seq(json.dumps({"answer": "Of 4 enquiries only 1 was contacted by a person. 1 open enquiry was never contacted. "
                                     "The top lost reason is Price (1 AI-proposed). Fix this and you get 37 more bookings."}))
    got = _ask(db, w, r, "Why are leads not getting converted?", llm)
    sent = json.loads(llm.calls[0]["user_message"])
    assert sent["facts"]["conversion"]["computed"] == "at question time"
    assert "conversion" in llm.calls[0]["system_prompt"]
    assert got["status"] == "answered" and got["dropped"] == 1 and "37" not in got["answer"]
    assert got["answer"].startswith("Of 4 enquiries only 1 was contacted") and got["prompt_version"] == "analyst-followup-v2"
    assert "conversion" not in r.facts           # the stored facts are not rewritten


def test_conversion_failure_never_fails_the_report_or_the_followup(db):
    """work_queue_service.counts (or anything in the block) raising: the report is still written with conversion marked
    unavailable, and a follow-up is still answered (the block retried, still unavailable, the model told so)."""
    _audit_table(db)
    w = world(db)
    with patch("app.services.work_queue_service.counts", side_effect=RuntimeError("boom")):
        r = _report(db, w)
        assert r.status == "ready" and r.facts["conversion"] == {"unavailable": True}
        llm = _Seq(json.dumps({"answer": "2 new leads came in; conversion data is unavailable for this report."}))
        got = _ask(db, w, r, "Why are leads not converting?", llm)
    assert got["status"] == "answered" and "unavailable" in got["answer"]
    assert json.loads(llm.calls[0]["user_message"])["facts"]["conversion"] == {"unavailable": True}
    assert "unavailable" in llm.calls[0]["system_prompt"]
