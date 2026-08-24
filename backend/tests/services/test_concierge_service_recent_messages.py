"""Test for the context-pollution fix in
concierge_service._get_recent_messages() / build_concierge_context().

Confirmed live: an AI draft that was never approved/sent (still pending
review, or rejected) was still pulled into the NEXT completion's context
as if it were part of the real conversation. One real conversation
accumulated 7 identical unsent "Thanks for your message! Let me check and
get right back to you." drafts in its last 20 messages -- each guest
follow-up then drafted against a prompt containing several copies of that
same failed boilerplate line as "recent conversation," compounding the
same failure into a self-perpetuating loop. A draft the guest never
actually saw isn't part of the conversation from their perspective.
"""
import uuid

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType
from app.services.concierge_service import build_concierge_context


def _make_tenant_guest_conv(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919876500020", name="Guest")
    db.add(guest); db.commit()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return tenant, guest, conv


class TestRecentMessagesExcludeUnsentDrafts:
    def test_unapproved_ai_draft_excluded_from_context(self, db):
        tenant, guest, conv = _make_tenant_guest_conv(db)
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
                        direction="inbound", channel="whatsapp", body="Hi"))
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
                        direction="outbound", channel="whatsapp", body="Never sent generic draft",
                        is_ai_generated=True, was_approved=None))  # still pending review
        db.commit()

        ctx = build_concierge_context(db, tenant_id=tenant.id, conversation_id=conv.id, guest_id=guest.id)
        bodies = [m["body"] for m in ctx["recent_messages"]]

        assert "Hi" in bodies
        assert "Never sent generic draft" not in bodies

    def test_rejected_ai_draft_excluded_from_context(self, db):
        tenant, guest, conv = _make_tenant_guest_conv(db)
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
                        direction="outbound", channel="whatsapp", body="Rejected bad draft",
                        is_ai_generated=True, was_approved=False))
        db.commit()

        ctx = build_concierge_context(db, tenant_id=tenant.id, conversation_id=conv.id, guest_id=guest.id)
        bodies = [m["body"] for m in ctx["recent_messages"]]

        assert "Rejected bad draft" not in bodies

    def test_approved_and_autonomous_ai_replies_still_included(self, db):
        """The fix must not hide replies the guest actually received --
        only ones they never saw."""
        tenant, guest, conv = _make_tenant_guest_conv(db)
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
                        direction="outbound", channel="whatsapp", body="Human-approved and sent",
                        is_ai_generated=True, was_approved=True))
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
                        direction="outbound", channel="whatsapp", body="Sent autonomously",
                        is_ai_generated=True, was_approved=True, sent_autonomously=True))
        db.commit()

        ctx = build_concierge_context(db, tenant_id=tenant.id, conversation_id=conv.id, guest_id=guest.id)
        bodies = [m["body"] for m in ctx["recent_messages"]]

        assert "Human-approved and sent" in bodies
        assert "Sent autonomously" in bodies

    def test_human_authored_messages_always_included(self, db):
        """Non-AI outbound (an agent typed this themselves) has no
        was_approved gate to worry about -- always real conversation."""
        tenant, guest, conv = _make_tenant_guest_conv(db)
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
                        direction="outbound", channel="whatsapp", body="Agent typed this manually",
                        is_ai_generated=False))
        db.commit()

        ctx = build_concierge_context(db, tenant_id=tenant.id, conversation_id=conv.id, guest_id=guest.id)
        bodies = [m["body"] for m in ctx["recent_messages"]]

        assert "Agent typed this manually" in bodies
