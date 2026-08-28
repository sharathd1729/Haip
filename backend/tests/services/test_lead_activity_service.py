"""Detailed per-lead report: get_lead_activity / get_agent_lead_cards.

Covers: chat-side scoping (human_owned conversation + this agent's own
outbound message), call-side scoping (Call.agent_id), one card per
Inquiry even when both a call and a chat touch it the same day, status
derivation from pipeline_stage, and tenant/agent isolation.
"""
import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.call import Call, CallDirection
from app.services.lead_activity_service import get_lead_activity, get_agent_lead_cards

TODAY = datetime.now(timezone.utc).date().isoformat()
NOON_TODAY = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit()
    return t


def _agent(db, tenant_id, name="Krisha"):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"{name.lower()}@t.com", name=name, role=UserRole.RESERVATIONS)
    db.add(u); db.commit()
    return u


def _guest(db, tenant_id, name="Chitra"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=f"+91{uuid.uuid4().int % 10**10:010d}")
    db.add(g); db.commit()
    return g


def _inquiry(db, tenant_id, guest_id, **overrides):
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, **overrides)
    db.add(i); db.commit()
    return i


class TestChatSideScoping:
    def test_human_owned_conversation_with_this_agents_message_is_included(self, db):
        t = _tenant(db)
        agent = _agent(db, t.id)
        guest = _guest(db, t.id)
        inquiry = _inquiry(db, t.id, guest.id)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id,
                             channel=ChannelType.WHATSAPP, human_owned=True)
        db.add(conv); db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id,
                        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                        body="Sure, checking availability now.", sender_id=agent.id, created_at=NOON_TODAY))
        db.commit()

        cards = get_agent_lead_cards(db, t.id, agent, TODAY)

        assert len(cards) == 1
        assert cards[0]["inquiry_id"] == inquiry.id
        assert cards[0]["guest_name"] == "Chitra"
        assert cards[0]["channel"] == "whatsapp"

    def test_bot_only_conversation_is_excluded(self, db):
        """human_owned=False -- no human agent has touched this thread."""
        t = _tenant(db)
        agent = _agent(db, t.id)
        guest = _guest(db, t.id)
        inquiry = _inquiry(db, t.id, guest.id)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id,
                             channel=ChannelType.WHATSAPP, human_owned=False)
        db.add(conv); db.commit()

        cards = get_agent_lead_cards(db, t.id, agent, TODAY)
        assert cards == []

    def test_another_agents_message_is_not_attributed_to_this_agent(self, db):
        t = _tenant(db)
        agent = _agent(db, t.id, "Krisha")
        other_agent = _agent(db, t.id, "Jishank")
        guest = _guest(db, t.id)
        inquiry = _inquiry(db, t.id, guest.id)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id,
                             channel=ChannelType.WHATSAPP, human_owned=True)
        db.add(conv); db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id,
                        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                        body="Handled by the other agent.", sender_id=other_agent.id, created_at=NOON_TODAY))
        db.commit()

        assert get_agent_lead_cards(db, t.id, agent, TODAY) == []
        assert len(get_agent_lead_cards(db, t.id, other_agent, TODAY)) == 1


class TestCallSideScoping:
    def test_call_attributed_to_agent_is_included(self, db):
        t = _tenant(db)
        agent = _agent(db, t.id)
        guest = _guest(db, t.id)
        inquiry = _inquiry(db, t.id, guest.id)
        db.add(Call(
            id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id, agent_id=agent.id,
            ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()), direction=CallDirection.OUTBOUND,
            from_number="+911111111111", to_number="+912222222222", ai_summary="Discussed a Coorg family trip.",
            created_at=NOON_TODAY,
        ))
        db.commit()

        cards = get_agent_lead_cards(db, t.id, agent, TODAY)
        assert len(cards) == 1
        assert cards[0]["channel"] == "call"
        assert "Coorg" in cards[0]["snippet"]


class TestOneCardPerInquiry:
    def test_call_and_chat_on_the_same_lead_yield_one_card(self, db):
        t = _tenant(db)
        agent = _agent(db, t.id)
        guest = _guest(db, t.id)
        inquiry = _inquiry(db, t.id, guest.id)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id,
                             channel=ChannelType.WHATSAPP, human_owned=True)
        db.add(conv); db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id,
                        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                        body="Following up after our call.", sender_id=agent.id,
                        created_at=NOON_TODAY + timedelta(hours=1)))
        db.add(Call(
            id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id, agent_id=agent.id,
            ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()), direction=CallDirection.OUTBOUND,
            from_number="+911111111111", to_number="+912222222222", ai_summary="Initial call.",
            created_at=NOON_TODAY,
        ))
        db.commit()

        cards = get_agent_lead_cards(db, t.id, agent, TODAY)
        assert len(cards) == 1
        # The later touch (the follow-up message) wins for channel/snippet.
        assert cards[0]["channel"] == "whatsapp"


class TestStatusDerivation:
    def test_closed_won_stage_reports_booked(self, db):
        t = _tenant(db)
        agent = _agent(db, t.id)
        guest = _guest(db, t.id)
        stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=t.id, key="sold", label="Sold", is_closed_won=True)
        db.add(stage); db.flush()
        inquiry = _inquiry(db, t.id, guest.id, stage_id=stage.id)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id,
                             channel=ChannelType.WHATSAPP, human_owned=True)
        db.add(conv); db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id,
                        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                        body="Confirmed!", sender_id=agent.id, created_at=NOON_TODAY))
        db.commit()

        cards = get_agent_lead_cards(db, t.id, agent, TODAY)
        assert cards[0]["status"] == "booked"

    def test_quoted_amount_without_a_closing_stage_reports_quoted(self, db):
        t = _tenant(db)
        agent = _agent(db, t.id)
        guest = _guest(db, t.id)
        inquiry = _inquiry(db, t.id, guest.id, quoted_amount=25000)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id,
                             channel=ChannelType.WHATSAPP, human_owned=True)
        db.add(conv); db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id,
                        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                        body="Here's the quote.", sender_id=agent.id, created_at=NOON_TODAY))
        db.commit()

        cards = get_agent_lead_cards(db, t.id, agent, TODAY)
        assert cards[0]["status"] == "quoted"
        assert cards[0]["quoted_amount"] == 25000.0


class TestTenantAndAgentIsolation:
    def test_get_lead_activity_without_agent_id_covers_every_agent(self, db):
        t = _tenant(db)
        a1 = _agent(db, t.id, "Krisha")
        a2 = _agent(db, t.id, "Jishank")
        for agent in (a1, a2):
            guest = _guest(db, t.id, f"Guest of {agent.name}")
            inquiry = _inquiry(db, t.id, guest.id)
            conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id,
                                 channel=ChannelType.WHATSAPP, human_owned=True)
            db.add(conv); db.flush()
            db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id,
                            direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                            body="Hi", sender_id=agent.id, created_at=NOON_TODAY))
        db.commit()

        all_cards = get_lead_activity(db, t.id, TODAY)
        assert {c["agent_name"] for c in all_cards} == {"Krisha", "Jishank"}

        scoped = get_lead_activity(db, t.id, TODAY, agent_id=a1.id)
        assert {c["agent_name"] for c in scoped} == {"Krisha"}

    def test_owner_and_manager_are_never_included_in_the_all_agents_view(self, db):
        t = _tenant(db)
        owner = User(id=str(uuid.uuid4()), tenant_id=t.id, email="owner@t.com", name="Owner", role=UserRole.OWNER)
        db.add(owner); db.commit()
        guest = _guest(db, t.id)
        inquiry = _inquiry(db, t.id, guest.id)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id, inquiry_id=inquiry.id,
                             channel=ChannelType.WHATSAPP, human_owned=True)
        db.add(conv); db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id,
                        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                        body="Hi", sender_id=owner.id, created_at=NOON_TODAY))
        db.commit()

        assert get_lead_activity(db, t.id, TODAY) == []
