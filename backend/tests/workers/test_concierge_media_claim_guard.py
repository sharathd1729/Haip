"""concierge_draft can never actually attach a photo/video/brochure to a
reply -- the draft Message it stores only ever has body text, no
media_url/media_type. Real case (Ratha, Sep 2026): a guest on Instagram
asked "Can yu plz share me the pictures" and the AI replied "Here are some
photos of our luxury caravan..." with nothing attached. Auto-sent, since
nothing caught it. This is the deterministic guard that now blocks it.

Mirrors test_concierge_soft_escalation.py's harness exactly.
"""
import uuid
from unittest.mock import patch

import pytest

from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.workers.tasks.concierge_draft import _check_no_media_claim, concierge_draft


def _setup(db, inbound_body="Can yu plz share me the pictures"):
    tenant = Tenant(
        id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
        ig_ai_mode_default="autonomous", ig_ai_confidence_threshold=0.5,
    )
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Rashmi")
    db.add(guest); db.commit()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        channel=ChannelType.INSTAGRAM, is_open=True, ai_mode="shadow",
    )
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel="instagram", body=inbound_body,
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class _FakeIntentLLM:
    async def complete(self, **kwargs):
        return {"tool_use": {"intent": "faq_answer"}}


def _reply_llm(reply, confidence=0.9, needs_human=False):
    class _Fake:
        async def complete(self, **kwargs):
            return {"tool_use": {"reply": reply, "confidence": confidence, "citations": [], "needs_human": needs_human}}
    return _Fake()


def _run(db, tenant, conv, inbound, reply_adapter):
    def _fake_get_llm(task):
        return _FakeIntentLLM() if task == "quick_classify" else reply_adapter
    with patch("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"), \
         patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay"), \
         patch("app.services.ai_rate_limit_service.check_send_allowed", return_value=(True, None)):
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)
    return db.query(Message).filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True).one()


@pytest.mark.parametrize("reply", [
    "Here are some photos of our luxury caravan. Let me know if you'd like to see more!",
    "Sure! Sharing the pictures below for your reference.",
    "Please find attached a few photos of the property.",
    "Sending you the pictures now, take a look!",
    "Here's a video of the caravan interior.",
    # Real escalation, same conversation: pressed on "still no photos," the
    # model invented a wholly fictitious delivery channel instead of
    # repeating the same lie.
    "Sorry the photos didn't seem to go through, so I've also resent the photos to your email.",
    "I've emailed you the pictures, please check your inbox.",
    "Just sent the brochure to your email for reference.",
])
def test_media_claims_are_caught(reply):
    assert _check_no_media_claim(reply)[0] is False


@pytest.mark.parametrize("reply", [
    "Our team will personally share some photos with you shortly!",
    "I don't have photos to share here, but a member of our team will send them.",
    "The caravan comes with AC, kitchenette and Wi-Fi.",
])
def test_ordinary_replies_are_not_flagged(reply):
    assert _check_no_media_claim(reply)[0] is True


def test_real_guest_reply_is_blocked_from_autosend(db):
    """The exact real-world reply, verbatim."""
    tenant, guest, conv, inbound = _setup(db)
    reply = ("Sure Rashmi, your caravan will have AC, kitchenette, WiFi, private deck, "
             "plus we'll add lights, flowers, balloons for the birthday. Anything else "
             "you'd like? Here are some photos of our luxury caravan. Let me know if "
             "you'd like to see more or have any other requests.")
    draft = _run(db, tenant, conv, inbound, _reply_llm(reply, confidence=0.95))

    assert draft.sent_autonomously is False
    assert draft.was_approved is None
    assert "claims to share media" in (draft.ai_needs_human_reason or "")
    assert draft.body == reply     # the agent still sees exactly what the model wrote, to edit or reject


def test_a_safe_reply_with_no_media_claim_still_autosends(db):
    tenant, guest, conv, inbound = _setup(db, inbound_body="What amenities does the caravan have?")
    reply = "Our team will personally share some photos with you shortly! Meanwhile, it comes with AC, kitchenette and WiFi."
    draft = _run(db, tenant, conv, inbound, _reply_llm(reply, confidence=0.95))

    assert draft.sent_autonomously is True, draft.ai_needs_human_reason
    assert draft.was_approved is True
