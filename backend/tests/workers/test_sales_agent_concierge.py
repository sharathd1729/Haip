"""The AI sales agent through the real concierge task: guardrails first.

Only the language model, Razorpay, the Celery queue and WhatsApp are replaced; records, pricing, the calendar, quotes, guards and
the draft are real. Pinned:
  * mode "off" (the default) changes nothing;
  * handoff price mode: no price is ever shown to the model and no quote is prepared;
  * grounded mode: only the figures package_pricing_service computed for this guest's dates, party and route may be stated;
  * no "available" without a free vehicle on the booking calendar (and none at all without a calendar check);
  * suggest prepares the quote on the lead and never sends; autopilot sends once, and falls back to suggest when a guard fails;
  * a refused quote, a B2B enquiry or a discount request hands the lead to a person; a staff quote is never replaced.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.conversation import Message
from app.models.guest import Guest
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Property, Stay
from app.models.sales_action import SalesAction
from app.models.task import Task
from app.services import quote_service as qs
from app.services import sales_action_service
from tests.test_quote_builder_pricing import START, coorg_48, price, pub, ratha
from tests.test_quote_send import approve_quote_template, connect_razorpay, rzp  # noqa: F401  (rzp is a fixture)
from tests.test_quotes_api import lead
from tests.workers.test_concierge_operational_data import Scripted, _conversation, _run

END = START + timedelta(days=2)


def _setup(db, *, price_mode="grounded", mode="suggest", auto_bookable=False, ready=False, link_policy="autonomous"):
    w = ratha(db)
    w.t.wa_ai_mode_default, w.t.wa_ai_confidence_threshold = "autonomous", 0.5
    # agent_policy.send_payment_link defaults to draft_for_approval; these tests are about the agent's own holds.
    w.t.brand_config = {"price_disclosure": price_mode, "sales_agent": {"mode": mode},
                        "agent_policy": {"modes": {"send_payment_link": link_policy}}}
    db.commit()
    if auto_bookable:
        pub(db, w, "package", "coorg-48", coorg_48(auto_bookable=True))
    if ready:
        connect_razorpay(db, w.t.id)
        approve_quote_template(db, w.t.id)
    return w


def _lead_conv(db, w, text):
    inq = lead(db, w.t.id)
    guest = db.query(Guest).filter_by(id=inq.guest_id).first()
    _, conv, (msg,) = _conversation(db, w.t, text, guest=guest)
    conv.inquiry_id = inq.id
    db.commit()
    return inq, conv, msg


def _more(db, w, conv, text):
    """A later guest message in the same conversation."""
    m = Message(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=conv.id, direction="inbound", channel="whatsapp", body=text,
                created_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db.add(m)
    db.commit()
    return m


def _coorg(**extra):
    return {"intent": "price_quote", "check_in": START.isoformat(), "check_out": END.isoformat(), "adults": 5, "children": 0,
            "destination": "Coorg", **extra}


def _ask(db, w, conv, msg, reply="The team will share your quote shortly.", classification=None):
    llm = Scripted(classification or _coorg(), reply={"reply": reply, "confidence": 0.95, "citations": [], "needs_human": False})
    with patch("app.workers.tasks.sales_agent_tasks.send_quote.delay") as agent_send:
        drafts, send = _run(db, w.t, conv, msg, llm)
    return llm, drafts[-1], send, agent_send


def _sales_fact(draft):
    return next(f for f in draft.grounded_facts if f["tool"] == "sales_agent")["result"]


@pytest.fixture()
def no_razorpay():
    with patch("app.adapters.payments.razorpay.create_payment_link", side_effect=AssertionError("no payment link in this mode")):
        yield


def test_mode_off_is_todays_behaviour(db, no_razorpay):
    w = _setup(db, mode="off")
    _, conv, msg = _lead_conv(db, w, "Coorg for 2 nights, 5 of us, what does it cost?")
    llm, draft, _, agent_send = _ask(db, w, conv, msg)
    assert not any(f["tool"] == "sales_agent" for f in draft.grounded_facts) and "SALES STEP" not in llm.system_prompt
    assert db.query(SalesAction).count() == 0 and db.query(InquiryQuote).filter_by(tenant_id=w.t.id).count() == 0
    agent_send.assert_not_called()


def test_handoff_price_mode_shows_no_price_and_prepares_no_quote(db, no_razorpay):
    w = _setup(db, price_mode="handoff")
    _, conv, msg = _lead_conv(db, w, "Coorg for 2 nights, 5 of us, what does it cost?")
    expected = price(db, w, "coorg-48", adults=5, destination_key="coorg")
    llm, draft, send, _ = _ask(db, w, conv, msg, reply=f"It comes to Rs {int(expected.total):,}.")
    assert _sales_fact(draft)["status"] == "price_by_team"
    assert str(int(expected.total)) not in llm.system_prompt and "PRICING RULE" in llm.system_prompt
    assert float(draft.ai_confidence) == 0.0 and "price leak" in draft.ai_needs_human_reason
    assert db.query(SalesAction).count() == 0 and db.query(InquiryQuote).filter_by(tenant_id=w.t.id).count() == 0
    send.assert_not_called()


def test_suggest_prepares_the_quote_on_the_lead_and_never_sends(db, no_razorpay):
    w = _setup(db)
    inq, conv, msg = _lead_conv(db, w, "Coorg for 2 nights, 5 of us. How much?")
    expected = price(db, w, "coorg-48", adults=5, destination_key="coorg")
    total = f"Rs {int(expected.total):,}"
    llm, draft, send, agent_send = _ask(db, w, conv, msg, reply=f"Coorg for those dates comes to {total} incl. GST. The team will share the quote shortly.")
    fact = _sales_fact(draft)
    assert fact["status"] == "quote_ready" and fact["requirement"]["package_key"] == "coorg-48"
    assert "has been prepared for the team to check" in llm.system_prompt
    assert f"total {expected.total} INR" in llm.system_prompt and "Billed at actuals, outside the total: Tolls and parking" in llm.system_prompt
    (q1,) = db.query(InquiryQuote).filter_by(tenant_id=w.t.id, inquiry_id=inq.id, option_rank=1).all()
    assert q1.created_by is None and q1.amount == expected.total and q1.snapshot["meta"]["source"] == "sales_agent"
    (action,) = db.query(SalesAction).filter_by(tenant_id=w.t.id).all()
    assert action.status == "pending" and action.mode == "suggest" and action.quote_id == q1.id and action.message_id == draft.id
    assert action.summary["total"] == str(expected.total) and action.summary["fallback"]["package_name"] == "Day rate"
    assert float(draft.ai_confidence) == 0.95 and not draft.ai_needs_human_reason      # the exact computed figure is allowed
    agent_send.assert_not_called()
    assert db.query(Task).filter(Task.tenant_id == w.t.id, Task.title.like("Call lead about pricing%")).count() == 0
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="sales_action.created").count() == 1


def test_grounded_mode_blocks_any_figure_the_price_engine_did_not_compute(db, no_razorpay):
    w = _setup(db)
    _, conv, msg = _lead_conv(db, w, "Coorg for 2 nights, 5 of us. How much?")
    _, draft, send, _ = _ask(db, w, conv, msg, reply="Coorg for those dates is Rs 65,000 all in.")
    assert float(draft.ai_confidence) == 0.0 and "65000" in draft.ai_needs_human_reason
    assert draft.was_approved is None


def test_no_available_claim_without_a_free_vehicle_and_the_nearest_dates_are_offered(db, no_razorpay):
    w = _setup(db)
    other = lead(db, w.t.id)
    for p in db.query(Property).filter_by(tenant_id=w.t.id).all():
        db.add(Stay(tenant_id=w.t.id, guest_id=other.guest_id, property_id=p.id, check_in=START, check_out=END, status="confirmed"))
    db.commit()
    _, conv, msg = _lead_conv(db, w, "Is Coorg free on those dates for 5?")
    llm, draft, send, _ = _ask(db, w, conv, msg, reply="Yes, those dates are available for your Coorg trip!")
    assert _sales_fact(draft)["status"] == "unavailable"
    check = next(f for f in draft.grounded_facts if f["tool"] == "check_availability" and f["args"].get("checkin"))
    assert check["source"] == "calendar" and not any(r["available"] for r in check["result"]) and check["alternatives"]
    assert "Nearest free dates" in llm.system_prompt
    assert float(draft.ai_confidence) == 0.0 and "no open property" in draft.ai_needs_human_reason
    assert db.query(InquiryQuote).filter_by(tenant_id=w.t.id).count() == 0
    send.assert_not_called()


def test_without_dates_an_available_claim_is_held(db, no_razorpay):
    w = _setup(db)
    _, conv, msg = _lead_conv(db, w, "Do you have caravans free?")
    _, draft, _, _ = _ask(db, w, conv, msg, reply="Yes, the caravan is available for your stay!",
                          classification={"intent": "general"})
    assert _sales_fact(draft)["status"] == "collecting"
    assert float(draft.ai_confidence) == 0.0 and "without a calendar check" in draft.ai_needs_human_reason


def test_autopilot_sends_once(db, rzp):
    w = _setup(db, mode="autopilot", auto_bookable=True, ready=True)
    inq, conv, msg = _lead_conv(db, w, "Coorg for 2 nights, 5 of us. How much?")
    llm, draft, send, agent_send = _ask(db, w, conv, msg, reply="I'm sending your quote and payment link in a moment.")
    assert _sales_fact(draft)["status"] == "quote_sending" and "being sent to them on WhatsApp" in llm.system_prompt
    send.assert_called_once()                                                     # the reply itself
    (action,) = db.query(SalesAction).filter_by(tenant_id=w.t.id).all()
    assert action.status == "sending" and action.mode == "autopilot" and action.hold_reasons == []
    agent_send.assert_called_once_with(tenant_id=w.t.id, action_id=action.id)
    assert rzp.create.call_count == 0                                             # nothing paid for before the task runs

    assert sales_action_service.deliver_autopilot(db, w.t.id, action.id) == {"status": "sent"}
    assert rzp.create.call_count == 2 and rzp.task.call_count == 1               # a link per option, one WhatsApp quote
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.sent").one().payload["actor"] == "ai_sales_agent"
    assert sales_action_service.deliver_autopilot(db, w.t.id, action.id) == {"status": "ignored"}

    # Not "Great, thanks!": a bare thank-you is an acknowledgement the concierge no longer drafts a reply to.
    msg2 = _more(db, w, conv, "When will the quote reach me?")
    _, draft2, _, agent_send2 = _ask(db, w, conv, msg2, reply="Your quote is in the message above.")
    assert _sales_fact(draft2)["status"] == "quote_already_sent"
    agent_send2.assert_not_called()
    assert db.query(SalesAction).filter_by(tenant_id=w.t.id).count() == 1 and rzp.create.call_count == 2


def test_autopilot_falls_back_to_suggest_when_the_route_needs_a_partner_check(db, rzp):
    w = _setup(db, mode="autopilot", ready=True)                                  # coorg-48 not marked auto-bookable
    _, conv, msg = _lead_conv(db, w, "Coorg for 2 nights, 5 of us. How much?")
    _, draft, _, agent_send = _ask(db, w, conv, msg)
    assert _sales_fact(draft)["status"] == "quote_ready"
    (action,) = db.query(SalesAction).filter_by(tenant_id=w.t.id).all()
    assert action.status == "pending" and any("partner" in r for r in action.hold_reasons)
    agent_send.assert_not_called()
    rzp.create.assert_not_called()


def test_autopilot_waits_for_a_person_when_the_reply_itself_is_held(db, rzp):
    w = _setup(db, mode="autopilot", auto_bookable=True, ready=True)
    _, conv, msg = _lead_conv(db, w, "Coorg for 2 nights, 5 of us. How much?")
    _, draft, send, agent_send = _ask(db, w, conv, msg, reply="Great news, your Coorg trip is booked!")
    assert float(draft.ai_confidence) == 0.0 and "booked or confirmed before any payment" in draft.ai_needs_human_reason
    assert all(c.kwargs.get("message_id") != draft.id for c in send.call_args_list)   # only the consult's holding reply may go
    agent_send.assert_not_called()
    (action,) = db.query(SalesAction).filter_by(tenant_id=w.t.id).all()
    assert action.status == "pending" and any("held for review" in r for r in action.hold_reasons)


def test_a_refused_quote_hands_the_lead_to_a_person(db, no_razorpay):
    w = _setup(db)
    _, conv, msg = _lead_conv(db, w, "Coorg for 3 nights, 5 of us. Price?")
    llm, draft, _, _ = _ask(db, w, conv, msg, reply="That comes to Rs 70,000.",
                            classification=_coorg(check_out=(START + timedelta(days=3)).isoformat()))
    fact = _sales_fact(draft)
    assert fact["status"] == "handoff" and "takes this forward personally" in llm.system_prompt
    assert "Package quote not possible" in llm.system_prompt and float(draft.ai_confidence) == 0.0
    assert db.query(SalesAction).count() == 0
    (task,) = db.query(Task).filter(Task.tenant_id == w.t.id, Task.title.like("Sales agent handed over%")).all()
    assert "above max nights" in task.title and task.inquiry_id is not None


@pytest.mark.parametrize("text, reply, why", [
    ("I'm a travel agent, 5 clients for Coorg, what commission do you give?", "Happy to help.", "travel agent"),
    ("Coorg for 2 nights, 5 of us -- any discount?", "We can give you 10% off!", "discount"),
])
def test_b2b_and_discount_requests_go_to_a_person_and_no_discount_is_offered(db, no_razorpay, text, reply, why):
    w = _setup(db)
    _, conv, msg = _lead_conv(db, w, text)
    _, draft, _, _ = _ask(db, w, conv, msg, reply=reply)
    assert _sales_fact(draft)["status"] == "handoff" and db.query(SalesAction).count() == 0
    assert db.query(Task).filter(Task.tenant_id == w.t.id, Task.title.like(f"%{why}%")).count() == 1
    if "%" in reply:
        assert float(draft.ai_confidence) == 0.0 and "offers a discount" in draft.ai_needs_human_reason


def test_a_quote_a_person_issued_is_never_replaced(db, no_razorpay):
    w = _setup(db)
    inq, conv, msg = _lead_conv(db, w, "Coorg for 2 nights, 5 of us. How much?")
    staff = qs.issue_quote(db, w.t.id, inq.id, price(db, w, "day-rate", adults=5), actor_id=w.owner.id)
    db.commit()
    llm, draft, _, _ = _ask(db, w, conv, msg)
    assert _sales_fact(draft)["status"] == "staff_quote" and "already working on their quote" in llm.system_prompt
    assert [q.id for q in db.query(InquiryQuote).filter_by(tenant_id=w.t.id, is_active=True).all()] == [staff.id]
    assert db.query(SalesAction).count() == 0
