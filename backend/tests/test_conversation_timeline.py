"""Tests for HAIP Inbox prototype-wiring plan, ticket 2: the merged
messages+calls conversation timeline."""
import json
import uuid

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.transcript import Transcript
from app.services.conversation_timeline_service import get_conversation_timeline


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _setup(db, tenant_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Priya", phone="+919999011111")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return guest, conv


class TestConversationTimelineService:
    def test_merges_messages_and_calls_chronologically(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest, conv = _setup(db, tenant_id)

        msg = Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
            direction="inbound", channel="whatsapp", body="Is the villa free next week?",
        )
        db.add(msg); db.commit()

        call = Call(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            ivr_provider="callerdesk", ivr_call_id=f"cd-{uuid.uuid4().hex[:8]}",
            direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
            duration_seconds=90, ai_summary="Guest asked about pricing.", conversion_probability=70,
        )
        db.add(call); db.commit()
        transcript = Transcript(
            id=str(uuid.uuid4()), tenant_id=tenant_id, call_id=call.id, provider="sarvam",
            turns=json.dumps([{"speaker": "Guest", "text": "Hello", "t0": 0, "t1": 2}]),
        )
        db.add(transcript); db.commit()

        result = get_conversation_timeline(db, tenant_id=tenant_id, conversation_id=conv.id)

        assert result is not None
        assert result["capped"] is False
        types = [item["type"] for item in result["items"]]
        assert "message" in types and "call" in types

        call_item = next(i for i in result["items"] if i["type"] == "call")
        assert call_item["call"]["ai_summary"] == "Guest asked about pricing."
        assert call_item["call"]["conversion_probability"] == 70
        assert call_item["call"]["turns"] == [{"speaker": "Guest", "text": "Hello", "t0": 0, "t1": 2}]

        msg_item = next(i for i in result["items"] if i["type"] == "message")
        assert msg_item["message"]["body"] == "Is the villa free next week?"

    def test_call_without_transcript_yields_empty_turns(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest, conv = _setup(db, tenant_id)
        call = Call(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            ivr_provider="callerdesk", ivr_call_id=f"cd-{uuid.uuid4().hex[:8]}",
            direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
            duration_seconds=30,
        )
        db.add(call); db.commit()

        result = get_conversation_timeline(db, tenant_id=tenant_id, conversation_id=conv.id)
        call_item = next(i for i in result["items"] if i["type"] == "call")
        assert call_item["call"]["turns"] == []

    def test_call_with_no_recording_yields_null_recording_url(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest, conv = _setup(db, tenant_id)
        call = Call(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            ivr_provider="callerdesk", ivr_call_id=f"cd-{uuid.uuid4().hex[:8]}",
            direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
            duration_seconds=30,
        )
        db.add(call); db.commit()

        result = get_conversation_timeline(db, tenant_id=tenant_id, conversation_id=conv.id)
        call_item = next(i for i in result["items"] if i["type"] == "call")
        assert call_item["call"]["recording_url"] is None
        assert "recording_s3_key" not in call_item["call"]  # internal storage path never exposed

    def test_call_with_local_recording_yields_stream_url(self, db, tenant_and_user):
        """HAIP Inbox full-parity pass, ticket 6: recording_url reuses
        calls.py's own _get_recording_url resolution -- for a local file
        path (dev/testing fallback), that resolves to the streaming
        endpoint, not the raw filesystem path."""
        tenant_id = _tenant_id(tenant_and_user)
        guest, conv = _setup(db, tenant_id)
        call = Call(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
            ivr_provider="callerdesk", ivr_call_id=f"cd-{uuid.uuid4().hex[:8]}",
            direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
            duration_seconds=30, recording_s3_key="/var/data/recordings/abc.mp3",
        )
        db.add(call); db.commit()

        result = get_conversation_timeline(db, tenant_id=tenant_id, conversation_id=conv.id)
        call_item = next(i for i in result["items"] if i["type"] == "call")
        assert call_item["call"]["recording_url"] == f"/api/v1/calls/{call.id}/recording"

    def test_unknown_conversation_returns_none(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        result = get_conversation_timeline(db, tenant_id=tenant_id, conversation_id=str(uuid.uuid4()))
        assert result is None

    def test_capped_at_limit(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest, conv = _setup(db, tenant_id)
        for i in range(5):
            db.add(Message(
                id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
                direction="inbound", channel="whatsapp", body=f"msg {i}",
            ))
        db.commit()

        result = get_conversation_timeline(db, tenant_id=tenant_id, conversation_id=conv.id, limit=3)
        assert result["capped"] is True
        assert len(result["items"]) == 3

    def test_cross_tenant_isolation(self, db, tenant_and_user):
        tenant_a = _tenant_id(tenant_and_user)
        tenant_b = str(uuid.uuid4())
        db.add(Tenant(id=tenant_b, name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()
        _, conv_b = _setup(db, tenant_b)

        result = get_conversation_timeline(db, tenant_id=tenant_a, conversation_id=conv_b.id)
        assert result is None


class TestConversationTimelineEndpoint:
    def test_happy_path(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest, conv = _setup(db, tenant_id)
        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
            direction="inbound", channel="whatsapp", body="Hi there",
        ))
        db.commit()

        resp = client.get(f"/api/v1/conversations/{conv.id}/timeline", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["type"] == "message"

    def test_not_found(self, client, tenant_and_user):
        resp = client.get(f"/api/v1/conversations/{uuid.uuid4()}/timeline", headers=_auth_headers(tenant_and_user))
        assert resp.status_code == 404
