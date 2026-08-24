"""Auto-send soft-escalation drafts, flag the lead for follow-up plan:
leads_service._batch_needs_agent_followup() / LeadCardSchema.
needs_agent_followup surface the same signal
concierge_draft.py's hard_block split now relies on -- a lead whose most
recent AI reply auto-sent (Message.sent_autonomously=True) but still
carries a persisted reason (Message.ai_needs_human_reason) needs a human
to follow up, even though the guest already got a reply. A lead with no
such message, or whose latest AI message has no reason (a clean autonomous
send), must not be flagged.
"""
import uuid

from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.services import leads_service


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"followup-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush()
    return t


def _make_guest(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="")
    db.add(g); db.flush()
    return g


def _make_inquiry(db, tenant_id, guest_id):
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT,
    )
    db.add(inq); db.flush()
    return inq


def _make_conversation(db, tenant_id, guest_id, inquiry_id):
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, inquiry_id=inquiry_id,
        channel=ChannelType.WHATSAPP, is_open=True,
    )
    db.add(conv); db.flush()
    return conv


def _make_ai_message(db, tenant_id, conversation_id, *, sent_autonomously, reason):
    m = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation_id,
        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
        body="reply", is_ai_generated=True,
        sent_autonomously=sent_autonomously, ai_needs_human_reason=reason,
    )
    db.add(m); db.flush()
    return m


class TestBatchNeedsAgentFollowup:
    def test_soft_escalated_auto_send_is_flagged(self, db):
        tenant = _make_tenant(db)
        guest = _make_guest(db, tenant.id)
        inq = _make_inquiry(db, tenant.id, guest.id)
        conv = _make_conversation(db, tenant.id, guest.id, inq.id)
        _make_ai_message(
            db, tenant.id, conv.id, sent_autonomously=True,
            reason="Guest wants a custom 20-person route -- needs personal planning.",
        )
        db.commit()

        result = leads_service._batch_needs_agent_followup(db, tenant.id, [inq.id])
        assert result == {inq.id: "Guest wants a custom 20-person route -- needs personal planning."}

    def test_clean_autonomous_send_not_flagged(self, db):
        """sent_autonomously=True but no reason -- a normal, unremarkable
        autonomous send. Must not show up as needing follow-up."""
        tenant = _make_tenant(db)
        guest = _make_guest(db, tenant.id)
        inq = _make_inquiry(db, tenant.id, guest.id)
        conv = _make_conversation(db, tenant.id, guest.id, inq.id)
        _make_ai_message(db, tenant.id, conv.id, sent_autonomously=True, reason=None)
        db.commit()

        result = leads_service._batch_needs_agent_followup(db, tenant.id, [inq.id])
        assert inq.id not in result

    def test_held_draft_not_flagged(self, db):
        """A hard-blocked draft (sent_autonomously=False) is a pending
        approval, not a follow-up flag -- different UI surface entirely."""
        tenant = _make_tenant(db)
        guest = _make_guest(db, tenant.id)
        inq = _make_inquiry(db, tenant.id, guest.id)
        conv = _make_conversation(db, tenant.id, guest.id, inq.id)
        _make_ai_message(db, tenant.id, conv.id, sent_autonomously=False, reason="price leak: '₹25000'")
        db.commit()

        result = leads_service._batch_needs_agent_followup(db, tenant.id, [inq.id])
        assert inq.id not in result

    def test_empty_inquiry_ids_returns_empty_dict(self, db):
        tenant = _make_tenant(db)
        assert leads_service._batch_needs_agent_followup(db, tenant.id, []) == {}

    def test_get_leads_pipeline_surfaces_the_flag_on_the_card(self, db):
        tenant = _make_tenant(db)
        guest = _make_guest(db, tenant.id)
        inq = _make_inquiry(db, tenant.id, guest.id)
        conv = _make_conversation(db, tenant.id, guest.id, inq.id)
        _make_ai_message(
            db, tenant.id, conv.id, sent_autonomously=True,
            reason="Frustrated guest -- needs a human touch.",
        )
        db.commit()

        response = leads_service.get_leads_pipeline(db, tenant.id)
        card = next(c for c in response.leads if c.inquiry_id == inq.id)
        assert card.needs_agent_followup is True
        assert card.needs_agent_followup_reason == "Frustrated guest -- needs a human touch."
