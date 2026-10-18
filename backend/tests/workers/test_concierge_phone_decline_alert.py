"""Phone-decline alert plan: a guest who explicitly refuses to share a
phone number on Instagram gets a dedicated Task + push alert so a human
follows up in the DM -- without blocking the AI's own reply (confirmed
live, it answers these fine). Mirrors test_concierge_soft_escalation.py's
harness exactly, on the Instagram channel this feature is scoped to.
"""
import uuid
from unittest.mock import patch

from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.models.task import Task
from app.models.tenant import Tenant
from app.workers.tasks.concierge_draft import concierge_draft


def _setup(db, *, inbound_body, channel=ChannelType.INSTAGRAM, threshold=0.5):
    tenant = Tenant(
        id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
        ig_ai_mode_default="autonomous",
        ig_ai_confidence_threshold=threshold,
        wa_ai_mode_default="autonomous",
        wa_ai_confidence_threshold=threshold,
    )
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Neil Moses")
    db.add(guest); db.commit()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        channel=channel, is_open=True, ai_mode="shadow",
    )
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel=str(getattr(channel, "value", channel)).lower(), body=inbound_body,
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class _FakeIntentLLM:
    async def complete(self, **kwargs):
        return {"tool_use": {"intent": "general"}}


class _FakeConciergeLLM:
    def __init__(self, reply, confidence=0.95):
        self.reply, self.confidence = reply, confidence

    async def complete(self, **kwargs):
        return {"tool_use": {
            "reply": self.reply, "confidence": self.confidence, "citations": [], "needs_human": False,
        }}


def _run(db, tenant_id, conv_id, message_id, reply_adapter, channel="instagram"):
    """Plain string ids only -- concierge_draft.run() closes the (shared,
    patched-in) db session in its own finally block, which detaches any ORM
    object the test loaded earlier. A second call in the same test must not
    touch attributes on objects from before the first call."""
    def _fake_get_llm(task):
        return _FakeIntentLLM() if task == "quick_classify" else reply_adapter

    send_target = (
        "app.workers.tasks.send_instagram_dm.send_instagram_dm.delay"
        if channel == "instagram"
        else "app.workers.tasks.send_whatsapp.send_whatsapp.delay"
    )
    with patch("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"), \
         patch(send_target):
        concierge_draft.run(message_id=message_id, conversation_id=conv_id, tenant_id=tenant_id)
    return (
        db.query(Message)
        .filter_by(conversation_id=conv_id, direction="outbound", is_ai_generated=True)
        .order_by(Message.created_at.desc())
        .first()
    )


class TestPhoneDeclineAlert:
    def test_creates_task_and_alert_without_blocking_the_send(self, db):
        tenant, guest, conv, inbound = _setup(
            db, inbound_body="No phone number kindly give me the details",
        )
        tenant_id, conv_id, message_id = tenant.id, conv.id, inbound.id  # captured before the task's own db.close() detaches these
        adapter = _FakeConciergeLLM(
            "Our team will personally work out the best options and share the details right here.",
        )
        draft = _run(db, tenant_id, conv_id, message_id, adapter)

        assert draft.sent_autonomously is True  # AI's own reply still goes out

        task = db.query(Task).filter_by(tenant_id=tenant_id, conversation_id=conv_id).first()
        assert task is not None
        assert task.title == "Guest declined phone number — Neil Moses"
        assert task.priority == "high"
        assert task.is_done is False
        # Real bug (Ratha, Sep 2026): with no due_date this Task never
        # appeared in My Day's "Due now" bucket, which hard-requires one.
        assert task.due_date is not None

    def test_no_task_for_an_ordinary_message(self, db):
        tenant, guest, conv, inbound = _setup(db, inbound_body="Is the caravan available this weekend?")
        tenant_id, conv_id, message_id = tenant.id, conv.id, inbound.id
        adapter = _FakeConciergeLLM("Let me check our availability for you.")
        _run(db, tenant_id, conv_id, message_id, adapter)

        assert db.query(Task).filter_by(tenant_id=tenant_id, conversation_id=conv_id).first() is None

    def test_scoped_to_instagram_only(self, db):
        """A WhatsApp conversation's identity IS a phone number -- 'declined
        to share a phone number' doesn't apply there."""
        tenant, guest, conv, inbound = _setup(
            db, inbound_body="No phone number kindly give me the details",
            channel=ChannelType.WHATSAPP,
        )
        tenant_id, conv_id, message_id = tenant.id, conv.id, inbound.id
        adapter = _FakeConciergeLLM("Sure, here are the details.")
        _run(db, tenant_id, conv_id, message_id, adapter, channel="whatsapp")

        assert db.query(Task).filter_by(tenant_id=tenant_id, conversation_id=conv_id).first() is None

    def test_deduplicates_on_repeated_decline(self, db):
        tenant, guest, conv, inbound1 = _setup(db, inbound_body="No phone number, please help here")
        tenant_id, conv_id, message_id_1 = tenant.id, conv.id, inbound1.id
        adapter = _FakeConciergeLLM("Sure, happy to help here.")
        _run(db, tenant_id, conv_id, message_id_1, adapter)

        inbound2 = Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv_id,
            direction="inbound", channel="instagram", body="Still don't have a number to share, sorry",
        )
        db.add(inbound2); db.commit()
        _run(db, tenant_id, conv_id, inbound2.id, adapter)

        tasks = db.query(Task).filter_by(tenant_id=tenant_id, conversation_id=conv_id).all()
        assert len(tasks) == 1

    def test_no_decline_task_when_the_guest_already_has_a_number(self, db):
        """A guest who wrote "won't share my number here" but had shared it (now captured as a signal) has not declined: the alert
        would put a stale "No phone shared" chip on the inbox."""
        from app.models.guest_identity import GuestIdentity
        tenant, guest, conv, inbound = _setup(db, inbound_body="won't share my number here, call 98450 12345")
        db.add(GuestIdentity(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, identity_type="phone",
                             identity_value="+919845012345", source="message_text", confidence=0.9))
        db.commit()
        tenant_id, conv_id, message_id = tenant.id, conv.id, inbound.id
        _run(db, tenant_id, conv_id, message_id, _FakeConciergeLLM("Thanks, our team will call you."))

        assert db.query(Task).filter_by(tenant_id=tenant_id, conversation_id=conv_id).first() is None
