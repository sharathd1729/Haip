"""Our own outbound campaign text is never read back as the guest's words (concierge-reply-v18, concierge-intent-v3,
leads360-summary-v10).

Live bug (Rathaa, Oct 2026, synthetic copy of the thread): the guest said "Hey!", later got our "Sept long weekend" campaign
("two caravans free ... 8 guests each, so 16 spots ... tell us your dates"), then asked only "Can you give barter
collaboration". The lead's trip details came back as "8 adults" and an "Ask a manager" proposed answer offered "open weekend
dates for 8 adults": the campaign had reached every prompt as a plain [OUTBOUND] line, indistinguishable from the guest.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.tenant import Tenant
from app.services import message_author as ma
from app.services.concierge_service import build_concierge_context
from app.workers.tasks.concierge_draft import _history_block, concierge_draft
from app.workers.tasks.generate_ai_summary import generate_ai_summary

CAMPAIGN = ("*Ratha* has two caravans free this long weekend. 8 guests each, so 16 spots across both. Coorg, Nandi Hills. "
            "Long weekend offer. Tell us your dates!")
T0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


# ── author labels ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw,expected", [
    (dict(direction="inbound"), ma.GUEST),
    (dict(direction="outbound", sender_kind="campaign"), ma.CAMPAIGN),
    (dict(direction="outbound", sender_name="Campaign: Sept_long weekend"), ma.CAMPAIGN),     # row older than sender_kind
    (dict(direction="outbound", channel_metadata={"kind": "campaign"}), ma.CAMPAIGN),
    (dict(direction="outbound", sender_kind="playbook"), ma.AUTOMATED),
    (dict(direction="outbound", sender_kind="system"), ma.AUTOMATED),
    (dict(direction="outbound", is_ai_generated=True), ma.AI),
    (dict(direction="outbound", sender_kind="ai_holding"), ma.AI),
    (dict(direction="outbound", sender_name="Asha"), ma.TEAM),
])
def test_every_message_names_its_author(kw, expected):
    direction = kw.pop("direction")
    assert ma.author_of(direction, **kw) == expected


@pytest.mark.parametrize("guest,ours,values,kept", [
    (["Can you give barter collaboration"], [CAMPAIGN], {"adults": 8, "party_size": 16}, {}),     # the live bug
    (["We are 8 friends"], [CAMPAIGN], {"adults": 8}, {"adults": 8}),                             # the guest said it too
    (["we are eight"], [CAMPAIGN], {"adults": 8}, {"adults": 8}),                                 # in words
    (["me and my wife"], [CAMPAIGN], {"adults": 2}, {"adults": 2}),                                # nobody wrote a number
    (["Can you give barter collaboration"], [], {"adults": 8}, {"adults": 8}),                    # nothing of ours to blame
])
def test_a_headcount_only_we_wrote_is_dropped(guest, ours, values, kept):
    out, dropped = ma.keep_guest_headcount(values, guest, ours)
    assert {k: v for k, v in out.items() if k in ma.HEADCOUNT_KEYS} == kept
    assert set(dropped) == set(values) - set(kept)


# ── the thread ────────────────────────────────────────────────────────────────

def _thread(db, *, mode="shadow"):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
               wa_ai_mode_default=mode, wa_ai_confidence_threshold=0.5, brand_config={})
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Guest A", phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
              lead_identified_at=T0)
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.WHATSAPP,
                     is_open=True, ai_mode=mode)
    db.add(c)
    db.flush()
    rows = [
        dict(direction="inbound", body="Hey!"),
        dict(direction="outbound", body="Hello! How can I assist you today?", is_ai_generated=True, was_approved=True,
             sent_autonomously=True),
        # A campaign row written before messages.sender_kind existed: only its sender name and metadata say what it is.
        dict(direction="outbound", body=CAMPAIGN, sender_name="Campaign: Sept_long weekend",
             channel_metadata={"kind": "campaign", "campaign_id": "c1"}),
        dict(direction="inbound", body="Can you give barter collaboration"),
    ]
    msgs = []
    for i, r in enumerate(rows):
        m = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, channel="whatsapp",
                    created_at=T0 + timedelta(days=i), **r)
        db.add(m)
        msgs.append(m)
    db.commit()
    return t, g, inq, c, msgs


class Scripted:
    def __init__(self, classification):
        self.classification, self.classifier_input, self.system_prompt = classification, None, None

    def __call__(self, task):
        outer = self

        class _LLM:
            provider = "scripted"

            async def complete(self, **kwargs):
                if task == "quick_classify":
                    outer.classifier_input = kwargs.get("user_message")
                    return {"tool_use": outer.classification}
                outer.system_prompt = kwargs.get("system_prompt")
                return {"tool_use": {"reply": "Thanks! The team looks at every collaboration request personally.",
                                     "confidence": 0.9, "citations": [], "needs_human": False}}
        return _LLM()


def test_concierge_prompt_and_details_never_take_the_campaign_as_the_guest(db):
    t, g, inq, c, msgs = _thread(db)
    llm = Scripted({"intent": "general", "adults": 8})            # the classifier read the campaign's "8 guests each"
    with patch("app.workers.tasks.concierge_draft.get_llm", llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), patch.object(db, "close"), \
         patch("app.services.push_service.send_to_tenant"), patch("app.workers.tasks.concierge_draft._emit_sse"), \
         patch("app.workers.tasks.concierge_draft._send_whatsapp_typing_indicator"), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        concierge_draft.run(message_id=msgs[-1].id, conversation_id=c.id, tenant_id=t.id)
    assert "[US: CAMPAIGN BROADCAST] " + CAMPAIGN in llm.system_prompt
    assert "[GUEST] Can you give barter collaboration" in llm.system_prompt
    assert "[OUTBOUND]" not in llm.system_prompt and "never treat its dates, group sizes" in llm.system_prompt.lower()
    assert "[US: CAMPAIGN BROADCAST]" in llm.classifier_input and "[US: AI ASSISTANT]" in llm.classifier_input
    assert "Party: 8 adults" not in llm.system_prompt                       # not "already known" from our own broadcast
    draft = db.query(Message).filter_by(conversation_id=c.id, is_ai_generated=True, was_approved=None).one()
    details = next(f["result"] for f in draft.grounded_facts if f.get("tool") == "conversation_details")
    assert "adults" not in details


def test_recent_messages_carry_the_author_and_stay_in_their_own_conversation(db):
    t, g, inq, c, msgs = _thread(db)
    other_t, other_g, _, other_c, _ = _thread(db)
    ctx = build_concierge_context(db, tenant_id=t.id, conversation_id=c.id, guest_id=g.id)
    assert [m["who"] for m in ctx["recent_messages"]] == [ma.GUEST, ma.AI, ma.CAMPAIGN, ma.GUEST]
    assert len(ctx["recent_messages"]) == 4                                   # nothing from the other workspace's thread
    block = _history_block(ctx["recent_messages"])
    assert "[US: CAMPAIGN BROADCAST] *Ratha*" in block and "[GUEST] Hey!" in block


def _summarise(db, tenant_id, inquiry_id, extracted):
    payload = {"summary": "The guest asked about a barter collaboration. No trip details yet. Reply yes or no.",
               "analysis": {}, "extracted": extracted}
    calls = []

    class _LLM:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return {"content": json.dumps(payload), "model": "fake"}

    with patch("app.workers.tasks.generate_ai_summary.get_llm", lambda task: _LLM()), \
         patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db), patch.object(db, "close"), \
         patch("app.services.lead_autopilot_service.queue_evaluation"):
        generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id)
    db.expire_all()
    return db.query(Inquiry).filter_by(id=inquiry_id).first(), calls


def test_summary_never_stores_the_campaigns_group_size_as_the_guests(db):
    t, g, inq, c, msgs = _thread(db)
    stored, calls = _summarise(db, t.id, inq.id, {"adults": 8, "party_size": 16, "special_requests": "barter collaboration"})
    assert stored.adults is None                                          # was 8, from "8 guests each"
    assert stored.special_requests == "barter collaboration"             # the guest's own words still land
    context = calls[0]["user_message"]
    assert "[us: campaign broadcast]" in context and "[guest]" in context and "[outbound]" not in context


def test_summary_keeps_a_headcount_the_guest_gave(db):
    t, g, inq, c, msgs = _thread(db)
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, channel="whatsapp", direction="inbound",
                   body="Actually we are 8 friends, can we come?", created_at=T0 + timedelta(days=9)))
    db.commit()
    stored, _ = _summarise(db, t.id, inq.id, {"adults": 8})
    assert stored.adults == 8


def test_summary_for_another_tenant_is_a_noop(db):
    t, g, inq, c, msgs = _thread(db)
    other, *_ = _thread(db)
    stored, calls = _summarise(db, other.id, inq.id, {"adults": 3})
    assert calls == [] and stored.adults is None
