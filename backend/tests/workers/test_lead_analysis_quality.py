"""Lead analysis (AI summary) stays current, consistent and honest about what was stated versus concluded.

The model is replaced by a scripted fake that records the context it was given, so each test can assert what the analysis was
built from (the real stage, the real booking state, the earlier summary, only messages the guest actually saw) and what happens to
what comes back (validated, never contradictory, never an impossible trip).
"""
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.services import leads_service
from app.workers.tasks import generate_ai_summary as gas
from app.workers.tasks.generate_ai_summary import generate_ai_summary

T0 = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)


def _setup(db, **inquiry_kw):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Chitra", phone="+919800000011")
    db.add(guest)
    db.flush()
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, source=InquirySource.WA_DIRECT, **inquiry_kw)
    db.add(inquiry)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, inquiry_id=inquiry.id,
                        channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.commit()
    return tenant.id, guest.id, inquiry.id, conv.id


def _msg(db, tenant_id, conv_id, direction, body, n, **kw):
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv_id, direction=direction,
                   channel=ChannelType.WHATSAPP, body=body, created_at=T0 + timedelta(minutes=n), **kw))
    db.commit()


class Fake:
    def __init__(self, summary="Guest wants a trip.", analysis=None, extracted=None, lead_analysis="Warm lead."):
        self.payload = {"summary": summary, "analysis": analysis or {}, "extracted": extracted or {}, "lead_analysis": lead_analysis}
        self.user_message = None

    def __call__(self, task):
        outer = self

        class _LLM:
            async def complete(self, **kwargs):
                outer.user_message = kwargs["user_message"]
                return {"content": json.dumps(outer.payload), "model": "fake"}
        return _LLM()


def _run(db, tenant_id, inquiry_id, fake):
    with patch("app.workers.tasks.generate_ai_summary.get_llm", fake), \
         patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)
    db.expire_all()
    return db.query(Inquiry).filter_by(id=inquiry_id).first()


# ─── the conversation it is built from ────────────────────────────────────────

def test_an_unsent_ai_draft_is_not_part_of_the_conversation(db):
    tid, gid, iid, cid = _setup(db)
    _msg(db, tid, cid, MessageDirection.INBOUND, "Can we bring a dog?", 0)
    _msg(db, tid, cid, MessageDirection.OUTBOUND, "DRAFT-NEVER-SENT we quoted 99999", 1, is_ai_generated=True, was_approved=None)
    _msg(db, tid, cid, MessageDirection.OUTBOUND, "REJECTED-DRAFT", 2, is_ai_generated=True, was_approved=False)
    _msg(db, tid, cid, MessageDirection.OUTBOUND, "SENT-BY-AI Dogs are welcome.", 3, is_ai_generated=True, was_approved=True)
    _msg(db, tid, cid, MessageDirection.OUTBOUND, "SENT-BY-HUMAN call me", 4, is_ai_generated=False)
    fake = Fake()
    _run(db, tid, iid, fake)
    assert "DRAFT-NEVER-SENT" not in fake.user_message and "REJECTED-DRAFT" not in fake.user_message
    assert "SENT-BY-AI" in fake.user_message and "SENT-BY-HUMAN" in fake.user_message


def test_an_early_message_with_the_dates_is_not_forgotten_in_a_long_conversation(db):
    tid, gid, iid, cid = _setup(db)
    _msg(db, tid, cid, MessageDirection.INBOUND, "We want 12-14 Dec, 4 adults", 0)
    for n in range(1, 20):
        _msg(db, tid, cid, MessageDirection.OUTBOUND if n % 2 else MessageDirection.INBOUND, f"filler message {n}", n)
    fake = Fake()
    _run(db, tid, iid, fake)
    assert "12-14 Dec, 4 adults" in fake.user_message                     # was cut off by the old 10-message window


def test_the_new_run_updates_the_previous_summary_rather_than_starting_over(db):
    tid, gid, iid, cid = _setup(db, ai_summary="Wants a Goa caravan 12-14 Dec for a birthday.",
                                ai_analysis={"intent": "birthday trip", "objection": "price", "unanswered_questions": ["pets"]})
    _msg(db, tid, cid, MessageDirection.INBOUND, "ok what about parking", 0)
    fake = Fake()
    _run(db, tid, iid, fake)
    assert "PREVIOUS SUMMARY" in fake.user_message and "Goa caravan 12-14 Dec" in fake.user_message
    assert "PREVIOUS ANALYSIS" in fake.user_message and "pets" in fake.user_message
    assert "UPDATE it" in gas.SYSTEM_PROMPT


def test_the_analysis_sees_the_real_stage_and_the_real_booking_state(db):
    tid, gid, iid, cid = _setup(db)
    stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key="sold", label="Sold", is_closed_won=True, category="valid")
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Goa", slug="g")
    db.add_all([stage, prop])
    db.flush()
    inq = db.query(Inquiry).filter_by(id=iid).first()
    inq.stage_id = stage.id
    stay = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=gid, property_id=prop.id, inquiry_id=iid,
                check_in=date.today() + timedelta(days=20), check_out=date.today() + timedelta(days=22), status="confirmed", total_amount=20000)
    db.add(stay)
    db.flush()
    db.add(StayPayment(id=str(uuid.uuid4()), tenant_id=tid, stay_id=stay.id, kind="payment", amount=5000, method="upi", paid_on=date.today()))
    db.commit()
    _msg(db, tid, cid, MessageDirection.INBOUND, "thanks!", 0)

    fake = Fake(analysis={"intent": "stay", "sentiment": "positive", "next_action": "Share arrival details"})
    result = _run(db, tid, iid, fake)

    assert "Stage: Sold (closed - won)" in fake.user_message
    assert "Booking status: confirmed, part-paid" in fake.user_message
    assert result.ai_analysis["booking_status"] == {"state": "confirmed", "payment": "partial", "stays": 1}   # computed, not the model's word

    stay.status = "cancelled"
    db.commit()
    result = _run(db, tid, iid, Fake(analysis={"intent": "stay"}))
    assert result.ai_analysis["booking_status"]["state"] == "cancelled" and result.ai_analysis["booking_status"]["payment"] is None


def test_an_enquiry_with_no_booking_says_so(db):
    tid, gid, iid, cid = _setup(db)
    _msg(db, tid, cid, MessageDirection.INBOUND, "hi", 0)
    fake = Fake(analysis={"intent": "x"})
    result = _run(db, tid, iid, fake)
    assert "no booking exists for this enquiry yet" in fake.user_message
    assert result.ai_analysis["booking_status"] == {"state": "none", "payment": None, "stays": 0}


# ─── what comes back is validated ─────────────────────────────────────────────

def test_analysis_values_the_product_branches_on_are_validated():
    cleaned = gas._clean_analysis({
        "intent": "  weekend stay ", "sentiment": "mostly positive", "reply_urgency": "ASAP",
        "objection": "", "next_action": "Call back",
        "unanswered_questions": ["pets?", "", None, "parking?"], "requirements": "not a list", "inferences": ["price sensitive"],
        "follow_up": "tomorrow",
    })
    assert cleaned["sentiment"] is None and cleaned["reply_urgency"] is None        # not in the vocabulary other code understands
    assert cleaned["objection"] is None and cleaned["intent"] == "weekend stay"
    assert cleaned["unanswered_questions"] == ["pets?", "parking?"] and cleaned["requirements"] == []
    assert cleaned["inferences"] == ["price sensitive"]
    assert gas._clean_analysis({"sentiment": " Hesitant ", "reply_urgency": "High"})["sentiment"] == "hesitant"


def test_stated_facts_and_inferences_are_kept_apart(db):
    tid, gid, iid, cid = _setup(db)
    _msg(db, tid, cid, MessageDirection.INBOUND, "4 of us, 12-14 Dec. Is it expensive?", 0)
    fake = Fake(
        analysis={"intent": "trip", "inferences": ["likely price-sensitive"], "unanswered_questions": ["is it expensive"]},
        extracted={"adults": 4, "check_in": "2026-12-12", "check_out": "2026-12-14", "budget": None},
    )
    result = _run(db, tid, iid, fake)
    assert result.adults == 4 and result.budget is None                      # the inference never became a stated budget
    assert result.ai_analysis["inferences"] == ["likely price-sensitive"]
    assert result.ai_analysis["unanswered_questions"] == ["is it expensive"]


def test_impossible_or_contradictory_dates_are_not_written(db):
    tid, gid, iid, cid = _setup(db)
    _msg(db, tid, cid, MessageDirection.INBOUND, "dec 14 to dec 12", 0)
    result = _run(db, tid, iid, Fake(extracted={"check_in": "2026-12-14", "check_out": "2026-12-12"}))
    assert result.check_in is None and result.check_out is None

    # a stated check-in that lands after the check-out already on file is also a misreading
    tid2, gid2, iid2, cid2 = _setup(db, check_in="2026-12-10", check_out="2026-12-12", dates_from_chat=True)
    _msg(db, tid2, cid2, MessageDirection.INBOUND, "arriving 20th", 0)
    result = _run(db, tid2, iid2, Fake(extracted={"check_in": "2026-12-20"}))
    assert (result.check_in, result.check_out) == ("2026-12-10", "2026-12-12")


def test_absurd_headcounts_and_budgets_are_not_written(db):
    tid, gid, iid, cid = _setup(db)
    _msg(db, tid, cid, MessageDirection.INBOUND, "hi", 0)
    result = _run(db, tid, iid, Fake(extracted={"adults": 4000, "children": -2, "budget": 9e12}))
    assert result.adults in (None, 1) and result.budget is None


def test_a_failed_model_call_keeps_the_existing_analysis(db):
    tid, gid, iid, cid = _setup(db, ai_summary="Existing summary.", ai_analysis={"intent": "kept"})
    _msg(db, tid, cid, MessageDirection.INBOUND, "hi", 0)

    class Boom:
        async def complete(self, **kw):
            raise RuntimeError("provider down")

    with patch("app.workers.tasks.generate_ai_summary.get_llm", lambda task: Boom()), \
         patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db), \
         patch.object(db, "close"), patch.object(db, "rollback"), \
         patch.object(generate_ai_summary, "retry", side_effect=RuntimeError("retry scheduled")):
        with pytest.raises(RuntimeError):
            generate_ai_summary.run(inquiry_id=iid, tenant_id=tid)
    db.expire_all()
    inq = db.query(Inquiry).filter_by(id=iid).first()
    assert inq.ai_summary == "Existing summary." and inq.ai_analysis == {"intent": "kept"}


def test_another_tenants_enquiry_is_untouched(db):
    tid, gid, iid, cid = _setup(db)
    other = _setup(db)[0]
    _msg(db, tid, cid, MessageDirection.INBOUND, "hi", 0)
    fake = Fake()
    with patch("app.workers.tasks.generate_ai_summary.get_llm", fake), \
         patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db), patch.object(db, "close"):
        generate_ai_summary.run(inquiry_id=iid, tenant_id=other)             # right id, wrong tenant
    assert fake.user_message is None
    assert db.query(Inquiry).filter_by(id=iid).first().ai_summary is None


# ─── how soon the analysis follows new messages ───────────────────────────────

def test_a_new_message_is_reflected_within_the_debounce_window_and_a_second_one_is_not_lost(monkeypatch):
    assert leads_service.SUMMARY_DEBOUNCE_TTL <= 600
    store: dict = {}
    monkeypatch.setattr(leads_service, "get_cached", lambda k: store.get(k))
    monkeypatch.setattr(leads_service, "set_cached", lambda k, v, ttl=None: store.__setitem__(k, v))
    with patch("app.workers.tasks.generate_ai_summary.generate_ai_summary.delay") as now, \
         patch("app.workers.tasks.generate_ai_summary.generate_ai_summary.apply_async") as later:
        assert leads_service.trigger_summary_refresh(MagicMock(), "i1", "t1", source="message") is True
        assert now.call_count == 1
        assert leads_service.trigger_summary_refresh(MagicMock(), "i1", "t1", source="message") is True      # inside the window
        assert later.call_args.kwargs["countdown"] == leads_service.SUMMARY_DEBOUNCE_TTL                   # one trailing catch-up
        assert leads_service.trigger_summary_refresh(MagicMock(), "i1", "t1", source="message") is False     # absorbed by it


def test_an_inquiry_whose_ai_is_off_still_gets_its_analysis_refreshed(db):
    from app.workers.tasks.concierge_draft import concierge_draft
    tid, gid, iid, cid = _setup(db)
    conv = db.query(Conversation).filter_by(id=cid).first()
    conv.ai_mode = "off"
    db.commit()
    _msg(db, tid, cid, MessageDirection.INBOUND, "any update?", 0)
    mid = db.query(Message).filter_by(conversation_id=cid).first().id
    with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), patch.object(db, "close"), \
         patch("app.services.leads_service.trigger_summary_refresh") as refresh:
        concierge_draft.run(message_id=mid, conversation_id=cid, tenant_id=tid)
    refresh.assert_called_once()
    assert refresh.call_args.kwargs["inquiry_id"] == iid and refresh.call_args.kwargs["source"] == "message"
    assert db.query(Message).filter_by(conversation_id=cid, is_ai_generated=True).count() == 0      # and no draft was written


def test_a_message_the_team_sends_refreshes_the_analysis(db, client, tenant_and_user, monkeypatch):
    from tests.conftest import seed_capabilities
    tenant = tenant_and_user["tenant"]
    seed_capabilities(db, tenant.id)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919800000022", name="G")
    db.add(guest)
    db.flush()
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, source=InquirySource.WA_DIRECT)
    db.add(inquiry)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, inquiry_id=inquiry.id,
                        channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.commit()
    with patch("app.services.leads_service.trigger_summary_refresh") as refresh, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        r = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "We have your dates, confirming now."},
                        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert r.status_code in (200, 201), r.text
    refresh.assert_called_once()
    assert refresh.call_args.args[1] == inquiry.id and refresh.call_args.kwargs["source"] == "message"
