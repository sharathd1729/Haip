"""Lead summary cost guards (AI cost audit, 8 Nov 2026).

lead_summary runs on paid Claude Sonnet in production (~$0.019 a call). It used to run on every trigger, with nothing new to
read, on "hi" DMs from people with no phone, and from classify before the call it was meant to read had been analysed.
"""

import inspect
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch


from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.inquiry_360 import InquiryQuote
from app.models.tenant import Tenant
from app.workers.tasks import call_analysis as call_analysis_module
from app.workers.tasks.concierge_draft import _persist_stated_details
from app.workers.tasks.generate_ai_summary import generate_ai_summary

PAYLOAD = {
    "summary": "The guest wants a weekend caravan trip for two. No dates yet. Ask for the dates.",
    "analysis": {},
    "extracted": {},
}


def _setup(db, *, lead=True, **inquiry_kw):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    guest = Guest(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name="G", lead_identified_at=datetime.now(UTC) if lead else None
    )
    db.add(guest)
    db.flush()
    inquiry = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, source=InquirySource.META_IG, **inquiry_kw
    )
    db.add(inquiry)
    db.flush()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, inquiry_id=inquiry.id, channel="instagram"
    )
    db.add(conv)
    db.commit()
    return tenant.id, inquiry.id, conv.id


def _message(db, tenant_id, conv_id, body):
    db.add(
        Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conv_id,
            direction=MessageDirection.INBOUND,
            channel="instagram",
            body=body,
        )
    )
    db.commit()


def _run(db, tenant_id, inquiry_id, **kw):
    calls = []

    class _LLM:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return {"content": json.dumps(PAYLOAD), "model": "fake"}

    with (
        patch("app.workers.tasks.generate_ai_summary.get_llm", lambda task: _LLM()),
        patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch("app.services.lead_autopilot_service.queue_evaluation"),
    ):
        generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id, **kw)
    db.expire_all()
    return calls


# ── "nothing new" fingerprint ────────────────────────────────────────────────────────────────────────────────────────
def test_unchanged_input_makes_no_second_llm_call(db):
    tid, iid, cid = _setup(db)
    _message(db, tid, cid, "hi, is the caravan free next month?")
    assert len(_run(db, tid, iid)) == 1
    assert db.query(Inquiry).filter_by(id=iid).first().ai_analysis.get("input_hash")
    assert _run(db, tid, iid) == []  # nothing new: no model call


def test_a_new_message_makes_a_new_run(db):
    tid, iid, cid = _setup(db)
    _message(db, tid, cid, "hi, is the caravan free next month?")
    _run(db, tid, iid)
    _message(db, tid, cid, "we are 4 people")
    assert len(_run(db, tid, iid)) == 1


def test_a_field_this_run_wrote_does_not_make_the_next_run_look_new(db):
    tid, iid, cid = _setup(db)
    _message(db, tid, cid, "we are 2 adults")
    with patch.dict(PAYLOAD, extracted={"adults": 2}):
        assert len(_run(db, tid, iid)) == 1
    assert db.query(Inquiry).filter_by(id=iid).first().adults == 2
    assert _run(db, tid, iid) == []


def test_manual_refresh_runs_even_when_nothing_changed(db):
    tid, iid, cid = _setup(db)
    _message(db, tid, cid, "hello")
    _run(db, tid, iid)
    assert len(_run(db, tid, iid, force=True)) == 1


def test_wrong_tenant_makes_no_call(db):
    tid, iid, cid = _setup(db)
    other, _, _ = _setup(db)
    assert _run(db, other, iid, force=True) == []


# ── leads and trip signals only ──────────────────────────────────────────────────────────────────────────────────────
def test_a_non_lead_dm_with_nothing_in_it_gets_no_summary(db):
    tid, iid, cid = _setup(db, lead=False)
    _message(db, tid, cid, "hi")
    assert _run(db, tid, iid) == []
    assert db.query(Inquiry).filter_by(id=iid).first().ai_summary is None


def test_a_non_lead_with_dates_or_a_party_size_is_summarised(db):
    tid, iid, cid = _setup(db, lead=False, check_in="2026-12-20")
    _message(db, tid, cid, "free on 20 Dec?")
    assert len(_run(db, tid, iid)) == 1
    tid, iid, cid = _setup(db, lead=False, adults=3)
    _message(db, tid, cid, "3 of us")
    assert len(_run(db, tid, iid)) == 1


def test_a_non_lead_with_a_quote_is_summarised(db):
    tid, iid, cid = _setup(db, lead=False)
    db.add(InquiryQuote(id=str(uuid.uuid4()), tenant_id=tid, inquiry_id=iid, amount=Decimal("50000")))
    db.commit()
    _message(db, tid, cid, "ok")
    assert len(_run(db, tid, iid)) == 1


def test_manual_refresh_summarises_a_non_lead(db):
    tid, iid, cid = _setup(db, lead=False)
    _message(db, tid, cid, "hi")
    assert len(_run(db, tid, iid, force=True)) == 1


# ── call path: summary after the call analysis, autopilot sees the analysis ───────────────────────────────────────────
# (classify/wrap_up became one task, tasks.analyze_call, in #156; the summary still runs once the call's own summary and
# next action are saved.)
def test_the_old_classify_name_does_not_trigger_the_summary():
    assert "trigger_summary_refresh(" not in inspect.getsource(call_analysis_module.classify)


def test_call_analysis_triggers_the_summary_with_the_call_analysis_saved(db):
    from tests.workers import call_analysis_harness as h

    tid, iid, _ = _setup(db)
    inquiry = db.query(Inquiry).filter_by(id=iid).first()
    call = h.call(db, tid, guest_id=inquiry.guest_id, inquiry_id=iid)
    seen = {}

    def _refresh(db, inquiry_id, tenant_id, source):
        stored = db.query(Call).filter_by(id=call.id).first()
        seen.update(inquiry_id=inquiry_id, source=source, summary=stored.ai_summary, next_action=stored.ai_next_action)
        return True

    llm = h.ScriptedLLM(h.answer(summary="Guest wants 2 nights in Dec.", next_action="Send the quote"))
    with patch("app.services.leads_service.trigger_summary_refresh", side_effect=_refresh):
        fx = h.run(db, tid, call.id, llm)

    assert seen == {
        "inquiry_id": iid,
        "source": "call",
        "summary": "Guest wants 2 nights in Dec.",
        "next_action": "Send the quote",
    }
    assert len(fx.autopilot) == 1


def test_autopilot_fingerprint_changes_once_the_call_is_analysed(db):
    from app.services import lead_autopilot_ai
    from app.services.lead_autopilot_service import StageMap

    tid, iid, _ = _setup(db)
    inquiry = db.query(Inquiry).filter_by(id=iid).first()
    call = Call(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        guest_id=inquiry.guest_id,
        inquiry_id=iid,
        ivr_provider="vobiz",
        ivr_call_id=f"c-{uuid.uuid4().hex[:8]}",
        direction=CallDirection.INBOUND,
        from_number="+919845663366",
        to_number="+912271264296",
        duration_seconds=45,
    )
    db.add(call)
    db.commit()
    stages = StageMap.load(db, tid)
    _, _, before = lead_autopilot_ai.build_context(db, tid, inquiry, stages)
    call.ai_summary = "Guest wants 2 nights."
    db.commit()
    _, _, after = lead_autopilot_ai.build_context(db, tid, inquiry, stages)
    assert before != after  # the read after wrap_up is not skipped as "already seen"


# ── concierge intent fields onto the enquiry ─────────────────────────────────────────────────────────────────────────
def test_stated_trip_fields_are_saved_with_the_summary_write_rules(db):
    tid, iid, _ = _setup(db, quoted_amount=Decimal("40000"))
    inquiry = db.query(Inquiry).filter_by(id=iid).first()
    _persist_stated_details(
        db,
        tid,
        inquiry,
        {
            "check_in": "2026-12-20",
            "check_out": "2026-12-22",
            "adults": 2,
            "occasion": "anniversary",
            "budget": 60000,
            "questions": ["price?"],
            "quoted_amount": 1,
        },
    )
    db.expire_all()
    inq = db.query(Inquiry).filter_by(id=iid).first()
    assert (str(inq.check_in), str(inq.check_out), inq.adults, inq.occasion) == (
        "2026-12-20",
        "2026-12-22",
        2,
        "anniversary",
    )
    assert inq.dates_from_chat is True and inq.budget == Decimal("60000")
    assert inq.quoted_amount == Decimal("40000")  # write-once, never from the intent call

    # a later message restates the dates: they move again (chat-derived)
    _persist_stated_details(db, tid, inq, {"check_in": "2026-12-27", "check_out": "2026-12-29"})
    db.expire_all()
    assert str(db.query(Inquiry).filter_by(id=iid).first().check_in) == "2026-12-27"


def test_a_call_date_is_never_overwritten_by_a_chat_date(db):
    tid, iid, _ = _setup(db, check_in="2026-12-10", check_out="2026-12-12", dates_from_chat=False)
    inquiry = db.query(Inquiry).filter_by(id=iid).first()
    _persist_stated_details(db, tid, inquiry, {"check_in": "2026-12-20", "check_out": "2026-12-22"})
    db.expire_all()
    assert str(db.query(Inquiry).filter_by(id=iid).first().check_in) == "2026-12-10"
