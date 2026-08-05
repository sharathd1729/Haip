"""Tests for HAIP Inbox full-parity pass, ticket 1:
- PATCH /conversations/{id} -- previously didn't exist at all; the frontend's
  Bulk Resolve button has called it since it was built, always 404ing
  silently.
- list_conversations' call-derived preview -- a call for a guest never
  showed up as the list preview text even after last_message_at got bumped
  separately, since the preview itself was still Message-only."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.models.tenant import Tenant


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _make_guest(db, tenant_id, phone="+919999011223"):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Priya", phone=phone)
    db.add(guest); db.commit()
    return guest


class TestPatchConversation:
    def test_toggles_is_open(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv); db.commit()

        resp = client.patch(f"/api/v1/conversations/{conv.id}", json={"is_open": False}, headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_open"] is False

        db.refresh(conv)
        assert conv.is_open is False

    def test_404_on_unknown_conversation(self, client, tenant_and_user):
        resp = client.patch(f"/api/v1/conversations/{uuid.uuid4()}", json={"is_open": False}, headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 404

    def test_cross_tenant_isolation(self, client, db, tenant_and_user):
        tenant_a = _tenant_id(tenant_and_user)
        tenant_b = str(uuid.uuid4())
        db.add(Tenant(id=tenant_b, name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()
        guest_b = Guest(id=str(uuid.uuid4()), tenant_id=tenant_b, name="Other", phone="+919999099999")
        db.add(guest_b); db.commit()
        conv_b = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_b, guest_id=guest_b.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv_b); db.commit()

        resp = client.patch(f"/api/v1/conversations/{conv_b.id}", json={"is_open": False}, headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 404  # tenant_a's token can't touch tenant_b's conversation


class TestCallDerivedPreview:
    def test_call_more_recent_than_last_message_wins_as_preview(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv); db.commit()

        old_msg_time = datetime.now(timezone.utc) - timedelta(hours=2)
        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
            direction="inbound", channel="whatsapp", body="Is the villa free?",
            created_at=old_msg_time,
        ))
        db.commit()

        call_time = datetime.now(timezone.utc)
        db.add(Call(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            ivr_provider="mcube", ivr_call_id=f"mc-{uuid.uuid4().hex[:8]}",
            direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
            duration_seconds=222, started_at=call_time.isoformat(),
        ))
        db.commit()

        resp = client.get("/api/v1/conversations", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json() if r["id"] == conv.id)
        assert "call" in row["last_message"].lower()
        assert "3m 42s" in row["last_message"]

    def test_message_more_recent_than_call_wins_as_preview(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id, phone="+919999022334")
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv); db.commit()

        old_call_time = datetime.now(timezone.utc) - timedelta(hours=2)
        db.add(Call(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            ivr_provider="mcube", ivr_call_id=f"mc-{uuid.uuid4().hex[:8]}",
            direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
            duration_seconds=90, started_at=old_call_time.isoformat(),
        ))
        db.commit()

        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
            direction="inbound", channel="whatsapp", body="Still interested, any update?",
        ))
        db.commit()

        resp = client.get("/api/v1/conversations", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json() if r["id"] == conv.id)
        assert row["last_message"] == "Still interested, any update?"

    def test_missed_call_preview_text(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id, phone="+919999033445")
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.VOICE, is_open=True)
        db.add(conv); db.commit()

        db.add(Call(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            ivr_provider="mcube", ivr_call_id=f"mc-{uuid.uuid4().hex[:8]}",
            direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
            duration_seconds=0, started_at=datetime.now(timezone.utc).isoformat(),
        ))
        db.commit()

        resp = client.get("/api/v1/conversations", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json() if r["id"] == conv.id)
        assert "Missed call" in row["last_message"]
