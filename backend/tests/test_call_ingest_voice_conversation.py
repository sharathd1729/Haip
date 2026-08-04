"""Tests for HAIP Inbox UI-fidelity pass, ticket 1: a guest whose only
touchpoint is a phone call gets a real, clickable Conversation row so the
inbox left-list (which only ever queries Conversation) can show them at
all -- previously call_ingest.py never created one."""
import uuid

from app.models.conversation import Conversation, ChannelType
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.workers.tasks.call_ingest import _find_or_create_voice_conversation


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_guest(db, tenant_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Voice Guest", phone="+919999011223")
    db.add(guest); db.commit()
    return guest


class TestFindOrCreateVoiceConversation:
    def test_creates_voice_conversation_for_guest_with_none(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)

        conv = _find_or_create_voice_conversation(db, tenant_id, guest)

        assert conv is not None
        assert conv.channel == ChannelType.VOICE
        assert conv.guest_id == guest.id
        assert conv.is_open is True

        reloaded = db.query(Conversation).filter_by(guest_id=guest.id, tenant_id=tenant_id).all()
        assert len(reloaded) == 1

    def test_idempotent_second_call_does_not_duplicate(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)

        first = _find_or_create_voice_conversation(db, tenant_id, guest)
        second = _find_or_create_voice_conversation(db, tenant_id, guest)

        assert first is not None
        assert second is None  # nothing created the second time

        all_convs = db.query(Conversation).filter_by(guest_id=guest.id, tenant_id=tenant_id).all()
        assert len(all_convs) == 1

    def test_does_not_create_when_guest_already_has_a_whatsapp_conversation(self, db, tenant_and_user):
        """A guest who messaged on WhatsApp first, then also called, keeps
        just their one real conversation -- the call shows up inside it via
        the merged timeline, not as a second voice-channel row."""
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        existing = Conversation(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            channel=ChannelType.WHATSAPP, is_open=True,
        )
        db.add(existing); db.commit()

        result = _find_or_create_voice_conversation(db, tenant_id, guest)

        assert result is None
        all_convs = db.query(Conversation).filter_by(guest_id=guest.id, tenant_id=tenant_id).all()
        assert len(all_convs) == 1
        assert all_convs[0].channel == ChannelType.WHATSAPP

    def test_tenant_isolation(self, db, tenant_and_user):
        tenant_a = _tenant_id(tenant_and_user)
        tenant_b = str(uuid.uuid4())
        db.add(Tenant(id=tenant_b, name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()

        guest_a = _make_guest(db, tenant_a)
        # Same guest_id value reused under a different tenant on purpose --
        # must not be treated as "already has a conversation" cross-tenant.
        guest_b = Guest(id=str(uuid.uuid4()), tenant_id=tenant_b, name="Other Guest", phone="+919999099999")
        db.add(guest_b); db.commit()

        conv_a = _find_or_create_voice_conversation(db, tenant_a, guest_a)
        conv_b = _find_or_create_voice_conversation(db, tenant_b, guest_b)

        assert conv_a is not None
        assert conv_b is not None
        assert conv_a.tenant_id == tenant_a
        assert conv_b.tenant_id == tenant_b
