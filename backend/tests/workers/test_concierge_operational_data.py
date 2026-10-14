"""The concierge answers from operational data: availability (with calendar blocks), the guest's own bookings, property facts,
what the guest already said, and (optionally) the live rate -- and it cannot promise what that data does not support.

Everything runs through the real task and real tables; only the language model is replaced by a scripted fake, which also lets
the tests read the exact prompt the model was given.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.property import BlockedDate, Property, PropertyAddOn, RatePlan, Stay
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.services import concierge_facts, price_policy
from app.workers.tasks.concierge_draft import _check_grounding, concierge_draft

TODAY = date.today()
CHECK_IN = (TODAY + timedelta(days=60)).isoformat()
CHECK_OUT = (TODAY + timedelta(days=62)).isoformat()


# ─── builders ──────────────────────────────────────────────────────────────────

def _tenant(db, *, mode="shadow", price_disclosure=None, **kw):
    cfg = {"price_disclosure": price_disclosure} if price_disclosure else {}
    t = Tenant(
        id=str(uuid.uuid4()), name="Ratha", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
        wa_ai_mode_default=mode, wa_ai_confidence_threshold=0.5, brand_config=cfg, **kw,
    )
    db.add(t)
    db.commit()
    return t


def _property(db, tenant, name="Goa Caravan", *, max_adults=6, price=10000, amenities=("AC", "Kitchenette"), addons=()):
    p = Property(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name=name, slug=f"p-{uuid.uuid4().hex[:6]}", type="villa",
        max_adults=max_adults, home_base="Bengaluru", amenities=list(amenities), city="Goa",
    )
    db.add(p)
    db.add(RatePlan(id=str(uuid.uuid4()), tenant_id=tenant.id, property_id=p.id, name="Standard", base_price_per_night=price))
    for n, price_ in addons:
        db.add(PropertyAddOn(id=str(uuid.uuid4()), tenant_id=tenant.id, property_id=p.id, name=n, price=price_))
    db.commit()
    return p


def _at(n: int) -> datetime:
    """Message n of a test conversation: whole seconds apart, so ordering never depends on the clock's resolution."""
    return datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=n * 10)


def _conversation(db, tenant, *bodies, property_id=None, guest=None):
    """A conversation with these inbound messages (oldest first) and no reply yet."""
    guest = guest or Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone=f"+9198{uuid.uuid4().int % 10**8:08d}", name="Priya")
    db.add(guest)
    db.flush()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True,
        ai_mode="shadow", property_id=property_id,
    )
    db.add(conv)
    db.flush()
    msgs = []
    for i, body in enumerate(bodies):
        m = Message(
            id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id, direction="inbound",
            channel="whatsapp", body=body, created_at=_at(i),
        )
        db.add(m)
        db.flush()
        msgs.append(m)
    db.commit()
    return guest, conv, msgs


class Scripted:
    """Stands in for get_llm: records every prompt, answers the classifier and the concierge from supplied dicts."""

    def __init__(self, classification, reply=None):
        self.classification = classification
        self.reply = reply or {"reply": "Sure, the team will confirm.", "confidence": 0.95, "citations": [], "needs_human": False}
        self.classifier_input = None
        self.system_prompt = None

    def __call__(self, task):
        outer = self

        class _LLM:
            async def complete(self, **kwargs):
                if task == "quick_classify":
                    outer.classifier_input = kwargs.get("user_message")
                    return {"tool_use": outer.classification}
                outer.system_prompt = kwargs.get("system_prompt")
                return {"tool_use": outer.reply}

        return _LLM()


def _run(db, tenant, conv, msg, llm, **kw):
    with patch("app.workers.tasks.concierge_draft.get_llm", llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as send,          patch.object(db, "close"):                      # the task closes its session; here the test shares it
        concierge_draft.run(message_id=msg.id, conversation_id=conv.id, tenant_id=tenant.id, **kw)
    drafts = db.query(Message).filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True).all()
    return drafts, send


def _avail(classification_extra=None):
    base = {"intent": "availability_check", "check_in": CHECK_IN, "check_out": CHECK_OUT, "adults": 2, "children": 0}
    base.update(classification_extra or {})
    return base


# ─── calendar blocks and bookings decide availability ─────────────────────────

def test_a_calendar_block_prevents_a_false_availability_promise(db):
    t = _tenant(db, mode="autonomous")
    prop = _property(db, t)
    db.add(BlockedDate(id=str(uuid.uuid4()), tenant_id=t.id, property_id=prop.id, blocked_from=CHECK_IN, blocked_to=CHECK_OUT, reason="offline_booking"))
    db.commit()
    _, conv, (msg,) = _conversation(db, t, f"Is the caravan free {CHECK_IN} to {CHECK_OUT}?")
    llm = Scripted(_avail(), reply={"reply": "Yes, those dates are available!", "confidence": 0.97, "citations": [], "needs_human": False})

    drafts, send = _run(db, t, conv, msg, llm)

    (draft,) = drafts
    fact = next(f for f in draft.grounded_facts if f["tool"] == "check_availability")
    assert [(p["property_name"], p["available"], p["reason"]) for p in fact["result"]] == [("Goa Caravan", False, "unavailable")]
    assert "NOT OPEN for these dates" in llm.system_prompt
    assert float(draft.ai_confidence) == 0.0 and draft.was_approved is None      # the false promise never leaves
    assert "available but the lookup found no open property" in draft.ai_needs_human_reason
    send.assert_not_called()


def test_a_cancelled_booking_frees_the_dates_and_a_confirmed_one_blocks_them(db):
    t = _tenant(db)
    prop = _property(db, t)
    other = Guest(id=str(uuid.uuid4()), tenant_id=t.id, phone="+919800000009", name="Other")
    db.add(other)
    db.flush()
    stay = Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=other.id, property_id=prop.id,
                check_in=date.fromisoformat(CHECK_IN), check_out=date.fromisoformat(CHECK_OUT), status="confirmed")
    db.add(stay)
    db.commit()
    from app.services.calculator_service import calculator_service as calc

    def status():
        return calc.availability_report(db, t.id, CHECK_IN, CHECK_OUT, 2)[0]["status"]

    assert status() == "unavailable"
    stay.status = "cancelled"
    db.commit()
    assert status() == "available"
    stay.status = "checked_in"
    db.commit()
    assert status() == "unavailable"


def test_availability_report_says_why_each_property_is_not_bookable(db):
    t = _tenant(db)
    small = _property(db, t, "Small", max_adults=2)
    blocked = _property(db, t, "Blocked", max_adults=8)
    open_ = _property(db, t, "Open", max_adults=8)
    no_rate = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="NoRate", slug="nr", type="villa", max_adults=8)
    db.add(no_rate)
    db.add(BlockedDate(id=str(uuid.uuid4()), tenant_id=t.id, property_id=blocked.id, blocked_from=CHECK_IN, blocked_to=CHECK_OUT))
    db.commit()
    from app.services.calculator_service import calculator_service as calc

    got = {r["property_name"]: r["status"] for r in calc.availability_report(db, t.id, CHECK_IN, CHECK_OUT, 5)}
    assert got == {"Small": "over_capacity", "Blocked": "unavailable", "Open": "available", "NoRate": "no_rate"}


def test_a_failed_availability_lookup_is_reported_and_no_availability_claim_survives_it(db):
    t = _tenant(db)
    _property(db, t)
    _, conv, (msg,) = _conversation(db, t, "Is it free that weekend?")
    llm = Scripted(_avail(), reply={"reply": "Yes, it's available for those dates.", "confidence": 0.9, "citations": [], "needs_human": False})
    with patch("app.services.calculator_service.calculator_service.search", side_effect=RuntimeError("rates down")):
        drafts, _ = _run(db, t, conv, msg, llm)
    (draft,) = drafts
    fact = next(f for f in draft.grounded_facts if f["tool"] == "check_availability")
    assert fact["lookup_failed"] is True
    assert "availability check FAILED" in llm.system_prompt
    assert "availability lookup failed" in draft.ai_needs_human_reason and float(draft.ai_confidence) == 0.0


# ─── the guest's own bookings ─────────────────────────────────────────────────

def test_pending_confirmed_paid_and_cancelled_bookings_are_distinguished_and_scoped_to_the_guest(db):
    t = _tenant(db)
    prop = _property(db, t)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=t.id, phone="+919811111111", name="Asha")
    other = Guest(id=str(uuid.uuid4()), tenant_id=t.id, phone="+919822222222", name="Ravi")
    other_tenant = _tenant(db)
    stranger = Guest(id=str(uuid.uuid4()), tenant_id=other_tenant.id, phone="+919833333333", name="Z")
    db.add_all([guest, other, stranger])
    db.flush()

    def stay(g, tenant, status, days, amount=20000):
        s = Stay(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=g.id, property_id=prop.id if tenant is t else _property(db, tenant).id,
                 check_in=TODAY + timedelta(days=days), check_out=TODAY + timedelta(days=days + 2), status=status, total_amount=amount,
                 internal_notes="staff only: difficult guest")
        db.add(s)
        db.flush()
        return s

    unpaid = stay(guest, t, "confirmed", 10)
    paid = stay(guest, t, "confirmed", 30)
    stay(guest, t, "cancelled", 50)
    stay(other, t, "confirmed", 12)                         # another guest of the same tenant
    stay(stranger, other_tenant, "confirmed", 14)           # another tenant
    db.add(StayPayment(id=str(uuid.uuid4()), tenant_id=t.id, stay_id=paid.id, kind="payment", amount=20000, method="upi", paid_on=TODAY))
    db.commit()

    fact = concierge_facts.guest_booking_facts(db, t.id, guest.id)
    rows = fact["result"]
    assert [(r["status"], r.get("payment_status")) for r in rows] == [
        ("confirmed", "unpaid"), ("confirmed", "paid"), ("cancelled", None),
    ]
    assert rows[0]["payment_in_words"] == "no payment received yet" and rows[2]["status_in_words"] == "cancelled"
    blob = str(fact)
    assert "staff only" not in blob and "20000" not in blob                      # nothing internal, no amounts
    assert len(rows) == 3                                                        # the other guest's and the other tenant's stays are absent

    _, conv, (msg,) = _conversation(db, t, "Is my booking confirmed?", guest=guest)
    llm = Scripted({"intent": "booking_status", "questions": ["is my booking confirmed"]})
    _run(db, t, conv, msg, llm)
    assert "THIS GUEST'S OWN BOOKINGS" in llm.system_prompt
    assert "no payment received yet" in llm.system_prompt and "cancelled" in llm.system_prompt
    assert "Ravi" not in llm.system_prompt and "staff only" not in llm.system_prompt


# ─── memory, multiple questions, property facts ───────────────────────────────

def test_dates_and_party_given_earlier_are_remembered_and_not_asked_again(db):
    t = _tenant(db)
    prop = _property(db, t)
    guest, conv, (first,) = _conversation(db, t, f"Hi! 4 adults, {CHECK_IN} to {CHECK_OUT}, it's a birthday trip to Goa")
    # we answered that, and the guest now sends a short follow-up
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id, direction="outbound", channel="whatsapp",
                   body="Lovely! Which caravan do you prefer?", is_ai_generated=False, created_at=_at(5)))
    db.commit()
    follow_up = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id, direction="inbound", channel="whatsapp", body="and is there parking?", created_at=_at(9))
    db.add(follow_up)
    db.commit()
    # what the classifier returns once it has read the whole conversation
    llm = Scripted({"intent": "faq_answer", "check_in": CHECK_IN, "check_out": CHECK_OUT, "adults": 4, "destination": "Goa",
                    "occasion": "birthday", "questions": ["is there parking"]})

    _run(db, t, conv, follow_up, llm)

    assert "4 adults, " + CHECK_IN in llm.classifier_input                  # the classifier saw the earlier message
    assert "ALREADY KNOWN FROM THIS CONVERSATION" in llm.system_prompt
    assert f"Travel dates: {CHECK_IN} → {CHECK_OUT}" in llm.system_prompt and "Party: 4 adults" in llm.system_prompt
    ask_block = llm.system_prompt.split("WHAT WE STILL NEED FROM THIS LEAD")[1].split("INSTRUCTIONS")[0]
    for asked in ("travel dates (check-in and check-out)", "how many guests (adults and children)",
                  "which property or destination", "any special requests or occasion"):
        assert asked not in ask_block                                             # all four were already given in chat


def test_every_question_in_a_message_is_listed_and_the_reply_budget_grows(db):
    t = _tenant(db)
    _property(db, t)
    _, conv, (msg,) = _conversation(db, t, "Pets allowed? What time is check-in? Is there a kitchen?")
    llm = Scripted({"intent": "faq_answer", "questions": ["pets allowed", "check-in time", "kitchen"]})
    _run(db, t, conv, msg, llm)
    assert "THE GUEST ASKED (3 things)" in llm.system_prompt
    for q in ("pets allowed", "check-in time", "kitchen"):
        assert f"- {q}" in llm.system_prompt
    assert "UNDER 80 WORDS" in llm.system_prompt

    _, conv2, (msg2,) = _conversation(db, t, "Pets allowed?")
    llm2 = Scripted({"intent": "faq_answer", "questions": ["pets allowed"]})
    _run(db, t, conv2, msg2, llm2)
    assert "UNDER 45 WORDS" in llm2.system_prompt


def test_property_facts_are_scoped_to_the_conversations_property_and_never_mix(db):
    t = _tenant(db)
    goa = _property(db, t, "Goa Caravan", amenities=("Sea view deck",), addons=[("Bonfire", 1500)])
    coorg = _property(db, t, "Coorg Caravan", amenities=("Plantation walk",))
    _, conv, (msg,) = _conversation(db, t, "What amenities do you have?", property_id=goa.id)
    llm = Scripted({"intent": "faq_answer", "questions": ["amenities"]})
    _run(db, t, conv, msg, llm)
    assert "Sea view deck" in llm.system_prompt and "Bonfire" in llm.system_prompt
    assert "Plantation walk" not in llm.system_prompt and "Coorg" not in llm.system_prompt
    assert "[withheld]" not in llm.system_prompt and "1500" not in llm.system_prompt          # handoff mode: add-on prices are hidden

    _, conv2, (msg2,) = _conversation(db, t, "What amenities do you have?")
    llm2 = Scripted({"intent": "faq_answer", "questions": ["amenities"]})
    _run(db, t, conv2, msg2, llm2)
    assert "Sea view deck" in llm2.system_prompt and "Plantation walk" in llm2.system_prompt   # no property known: both, each under its own name


def test_a_past_or_impossible_date_is_never_checked_and_the_guest_is_asked(db):
    t = _tenant(db)
    _property(db, t)
    _, conv, (msg,) = _conversation(db, t, "Free on 3 January?")
    past = (TODAY - timedelta(days=30)).isoformat()
    llm = Scripted(_avail({"check_in": past, "check_out": (TODAY - timedelta(days=28)).isoformat()}))
    with patch("app.services.calculator_service.calculator_service.search") as search:
        drafts, _ = _run(db, t, conv, msg, llm)
    search.assert_not_called()
    assert "have already passed" in llm.system_prompt
    assert not any(f["tool"] == "check_availability" and f.get("args", {}).get("checkin") for f in drafts[0].grounded_facts)


# ─── pricing: handoff by default, live figures only in grounded mode ──────────

def _kb_with_old_rate(monkeypatch):
    stale = [{"text": "Weekend rate is ₹8,000 per night for the caravan. Pets welcome.", "source": "pricing", "score": 0.9}]
    monkeypatch.setattr("app.services.knowledge_service.search_snippets", lambda *a, **k: stale)
    from app.services.knowledge_service import SearchOutcome
    monkeypatch.setattr("app.services.knowledge_service.search_detailed",
                        lambda *a, **k: SearchOutcome(hits=[{"id": "k", "category": "pricing", "question": None,
                                                              "content": "Weekend rate is ₹8,000 per night for the caravan. Pets welcome.",
                                                              "source": "document", "score": 0.9}]))


def test_default_mode_never_shows_the_model_a_price_and_old_document_rates_are_removed(db, monkeypatch):
    _kb_with_old_rate(monkeypatch)
    t = _tenant(db)
    _property(db, t, price=10000)
    _, conv, (msg,) = _conversation(db, t, "What would 2 nights cost?")
    llm = Scripted(_avail({"intent": "price_quote"}), reply={"reply": "It's ₹20,000 for the two nights.", "confidence": 0.95, "citations": [], "needs_human": False})
    drafts, _ = _run(db, t, conv, msg, llm)
    assert "8,000" not in llm.system_prompt and "10000" not in llm.system_prompt and "PRICING RULE" in llm.system_prompt
    assert "Pets welcome" in llm.system_prompt                                 # the rest of the passage is still used
    assert float(drafts[0].ai_confidence) == 0.0 and "price leak" in drafts[0].ai_needs_human_reason


def test_grounded_mode_uses_the_live_quote_and_blocks_the_old_document_rate(db, monkeypatch):
    _kb_with_old_rate(monkeypatch)
    t = _tenant(db, price_disclosure="grounded")
    prop = _property(db, t, price=10000)
    _, conv, (msg,) = _conversation(db, t, "What would 2 nights cost?", property_id=prop.id)

    good = Scripted(_avail({"intent": "price_quote"}),
                    reply={"reply": "For those 2 nights the total comes to ₹22,400 including GST.", "confidence": 0.95, "citations": [], "needs_human": False})
    drafts, _ = _run(db, t, conv, msg, good)
    assert "CURRENT PRICING" in good.system_prompt and "22400" in good.system_prompt
    assert "8,000" not in good.system_prompt                                   # the document's rate never reaches the model
    assert float(drafts[0].ai_confidence) == 0.95 and not drafts[0].ai_needs_human_reason

    _, conv2, (msg2,) = _conversation(db, t, "What would 2 nights cost?", property_id=prop.id)
    stale = Scripted(_avail({"intent": "price_quote"}),
                     reply={"reply": "The weekend rate is ₹8,000 per night.", "confidence": 0.95, "citations": [], "needs_human": False})
    drafts2, _ = _run(db, t, conv2, msg2, stale)
    assert float(drafts2[0].ai_confidence) == 0.0
    assert "not present in grounded_facts" in drafts2[0].ai_needs_human_reason or "figure(s) not from the live rate" in drafts2[0].ai_needs_human_reason


def test_grounded_mode_without_a_live_price_says_the_rate_needs_confirming(db):
    t = _tenant(db, price_disclosure="grounded")
    _property(db, t)
    _, conv, (msg,) = _conversation(db, t, "How much is it?")
    llm = Scripted({"intent": "price_quote", "questions": ["price"]},
                   reply={"reply": "It's ₹12,000 a night.", "confidence": 0.95, "citations": [], "needs_human": False})
    drafts, _ = _run(db, t, conv, msg, llm)
    assert "no live price was fetched" in llm.system_prompt and "the rate needs confirming" in llm.system_prompt
    assert float(drafts[0].ai_confidence) == 0.0                                  # an invented figure is blocked


def test_price_mode_defaults_to_handoff_and_rejects_nonsense():
    assert price_policy.price_mode(MagicMock(brand_config={})) == "handoff"
    assert price_policy.price_mode(MagicMock(brand_config={"price_disclosure": "anything"})) == "handoff"
    assert price_policy.price_mode(MagicMock(brand_config={"price_disclosure": "grounded"})) == "grounded"


def test_a_figure_cannot_be_supported_by_a_fragment_of_an_id_or_a_headcount():
    facts = [{"tool": "get_quote", "args": {"property_id": "ab-4000-cd"}, "result": {"total": "22400", "adults": 4}}]
    ok, _ = _check_grounding("The total is ₹22,400.", facts)
    assert ok
    ok, reason = _check_grounding("That is ₹4,000.", facts)
    assert not ok and "4000" in reason


# ─── output safety, retries and approval controls ─────────────────────────────

@pytest.mark.parametrize("bad", [
    {"reply": ["not", "text"], "confidence": 0.99, "needs_human": False},
    {"reply": "Hello!", "confidence": "very high", "needs_human": False},
    {"reply": "Hello!", "confidence": 7, "needs_human": False},
    {"reply": "Hello!", "confidence": 0.99, "needs_human": "no"},
    {"reply": "x" * 3000, "confidence": 0.99, "needs_human": False},
])
def test_malformed_model_output_is_never_sent_and_never_breaks_the_task(db, bad):
    t = _tenant(db, mode="autonomous")
    _, conv, (msg,) = _conversation(db, t, "Hi")
    llm = Scripted({"intent": "general"}, reply=bad)
    drafts, send = _run(db, t, conv, msg, llm)
    (draft,) = drafts
    assert float(draft.ai_confidence) == 0.0 and draft.was_approved is None
    assert "malformed model output" in draft.ai_needs_human_reason or "no usable content" in draft.ai_needs_human_reason
    send.assert_not_called()


def test_a_reply_wrapped_in_json_is_unwrapped_not_sent_raw(db):
    t = _tenant(db)
    _, conv, (msg,) = _conversation(db, t, "Hi")
    llm = Scripted({"intent": "general"}, reply={"reply": '{"reply": "Hello Priya!", "confidence": 0.9}', "confidence": 0.9, "needs_human": False})
    (draft,), _ = _run(db, t, conv, msg, llm)
    assert draft.body == "Hello Priya!"


def test_a_retried_task_does_not_draft_or_send_a_second_reply(db):
    t = _tenant(db, mode="autonomous")
    _, conv, (msg,) = _conversation(db, t, "What time is check-in?")
    llm = Scripted({"intent": "faq_answer"}, reply={"reply": "Check-in is from 2 pm.", "confidence": 0.95, "citations": [], "needs_human": False})
    drafts, send = _run(db, t, conv, msg, llm)
    assert len(drafts) == 1 and send.call_count == 1

    drafts, send = _run(db, t, conv, msg, llm)                    # Celery retries / redelivers the same task
    assert len(drafts) == 1 and send.call_count == 0

    drafts, send = _run(db, t, conv, msg, llm, force=True)       # an agent explicitly asks for another draft
    assert len(drafts) == 2


def test_shadow_mode_and_the_kill_switch_still_hold_back_a_confident_reply(db):
    shadow = _tenant(db, mode="shadow")
    _, conv, (msg,) = _conversation(db, shadow, "What time is check-in?")
    llm = Scripted({"intent": "faq_answer"}, reply={"reply": "Check-in is from 2 pm.", "confidence": 0.99, "citations": [], "needs_human": False})
    (draft,), send = _run(db, shadow, conv, msg, llm)
    assert draft.was_approved is None and draft.sent_autonomously is False
    send.assert_not_called()

    killed = _tenant(db, mode="autonomous", ai_kill_switch=True)
    _, conv2, (msg2,) = _conversation(db, killed, "What time is check-in?")
    (draft2,), send2 = _run(db, killed, conv2, msg2, llm)
    assert draft2.was_approved is None
    send2.assert_not_called()


def test_the_knowledge_base_being_unreachable_is_not_reported_to_the_model_as_no_answer(db, monkeypatch):
    from app.services.knowledge_service import SearchOutcome
    monkeypatch.setattr("app.services.knowledge_service.search_detailed",
                        lambda *a, **k: SearchOutcome(status="embedding_unavailable", detail="timeout"))
    t = _tenant(db)
    _, conv, (msg,) = _conversation(db, t, "Do you allow pets?")
    llm = Scripted({"intent": "faq_answer", "questions": ["pets"]})
    _run(db, t, conv, msg, llm)
    assert "could not be searched just now" in llm.system_prompt
