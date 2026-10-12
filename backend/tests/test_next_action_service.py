"""Tests for HAIP_AI_Autonomy_Plan.md Phase 2, ticket 5: next_action_service.py
-- the generalised (moved from call_service.py) derive_recommended_action(),
plus the new get_call_actions() read-side reshaping into the
RecommendedAction[] shape AIRecommendationCard.tsx expects.
"""
import uuid

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.services.next_action_service import derive_recommended_action, get_call_actions


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_call(db, tenant_id, guest_id=None):
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        ivr_provider="callerdesk", ivr_call_id=f"cd-{uuid.uuid4().hex[:8]}",
        direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
        duration_seconds=120,
    )
    db.add(call); db.commit()
    return call


def _make_pending_draft(db, tenant_id, guest_id, body="Draft reply about the villa."):
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
        direction="outbound", channel="whatsapp", body=body,
        is_ai_generated=True, was_approved=None,
    )
    db.add(msg); db.commit()
    return conv, msg


class TestDeriveRecommendedAction:
    def test_pending_draft_yields_send_whatsapp_draft(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone="+919999000010", name="Guest A")
        db.add(guest); db.commit()
        conv, draft = _make_pending_draft(db, tenant_id, guest.id)
        call = _make_call(db, tenant_id, guest_id=guest.id)

        action_type, target_id = derive_recommended_action(db, call)

        assert action_type == "send_whatsapp_draft"
        assert target_id == draft.id

    def test_no_pending_draft_yields_none(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone="+919999000011", name="Guest B")
        db.add(guest); db.commit()
        call = _make_call(db, tenant_id, guest_id=guest.id)

        action_type, target_id = derive_recommended_action(db, call)

        assert action_type is None
        assert target_id is None

    def test_no_guest_id_yields_none(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        call = _make_call(db, tenant_id, guest_id=None)

        action_type, target_id = derive_recommended_action(db, call)

        assert action_type is None
        assert target_id is None

    def test_tenant_isolation_draft_in_other_tenant_not_picked_up(self, db, tenant_and_user):
        """A call in tenant A must never surface a draft that actually lives
        in tenant B's conversation, even if (implausibly) the guest_id string
        matched -- the join filters on Conversation.tenant_id == call.tenant_id."""
        tenant_a = _tenant_id(tenant_and_user)
        tenant_b = str(uuid.uuid4())
        from app.models.tenant import Tenant
        db.add(Tenant(id=tenant_b, name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()

        # The guest row has to exist (conversations.guest_id and calls.guest_id are foreign keys); it belongs to
        # tenant B, and tenant A's call then refers to it too, which is the cross-tenant case under test.
        shared_guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_b, name="Shared Guest")
        db.add(shared_guest); db.flush()
        shared_guest_id = shared_guest.id
        # Draft lives under tenant B's conversation.
        conv_b = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_b, guest_id=shared_guest_id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv_b); db.flush()
        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant_b, conversation_id=conv_b.id,
            direction="outbound", channel="whatsapp", body="tenant B draft",
            is_ai_generated=True, was_approved=None,
        ))
        db.commit()

        # Call lives under tenant A, referencing the same guest_id value.
        call = _make_call(db, tenant_a, guest_id=shared_guest_id)

        action_type, target_id = derive_recommended_action(db, call)

        assert action_type is None
        assert target_id is None


class TestGetCallActions:
    def test_happy_path_shape_matches_recommendation_card(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone="+919999000012", name="Guest C")
        db.add(guest); db.commit()
        conv, draft = _make_pending_draft(db, tenant_id, guest.id)
        call = _make_call(db, tenant_id, guest_id=guest.id)
        call.recommended_action_type = "send_whatsapp_draft"
        call.recommended_action_target_id = draft.id
        db.commit()

        actions = get_call_actions(db, call)

        assert len(actions) == 1
        action = actions[0]
        assert action["action_type"] == "send_whatsapp_draft"
        assert action["label"]
        assert action["confirm"] is True
        assert action["action_config"]["message_id"] == draft.id
        assert action["action_config"]["conversation_id"] == conv.id

    def test_no_recommended_action_type_yields_empty_list(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        call = _make_call(db, tenant_id)

        assert get_call_actions(db, call) == []

    def test_target_message_deleted_yields_empty_list(self, db, tenant_and_user):
        """Stale pointer (message since deleted/reassigned) degrades to no
        actions rather than a broken/None action_config."""
        tenant_id = _tenant_id(tenant_and_user)
        call = _make_call(db, tenant_id)
        call.recommended_action_type = "send_whatsapp_draft"
        call.recommended_action_target_id = str(uuid.uuid4())  # no such message
        db.commit()

        assert get_call_actions(db, call) == []
