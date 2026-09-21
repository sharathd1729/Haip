"""
Tests for send_instagram_dm's Meta error handling.

Confirmed live on Ratha: a guest ("Sharath Chandra") went quiet for 5.5
days, then every subsequent outbound Instagram send -- both AI-drafted
and agent-typed -- was rejected by Meta with a 403. The token and the
guest's Instagram ID were both independently verified as valid (a direct
Graph API profile read for the exact IGSID returned 200). The real cause
is Instagram's 24-hour messaging window: a business can't message a user
first once more than 24h have passed since that user's last message.

Before this fix, the task retried the send up to 3 times (all doomed,
same rejection every time) and finally stored httpx's generic exception
summary ("Max retries exceeded: Client error '403 Forbidden'...") as
delivery_error -- even though meta_graph.py's _post() already logs the
real Meta error body, it never made it into the message the agent sees.
"""
import uuid
from unittest.mock import patch, MagicMock

import httpx
import pytest
from sqlalchemy import text

from app.core.encryption import encrypt_credentials
from app.models.conversation import Conversation, Message, ChannelType, MessageDeliveryState
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.models.integration import Integration
from app.workers.tasks.send_instagram_dm import send_instagram_dm


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_conversation_with_pending_message(db, tenant_id, igsid="ig-user-123"):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Sharath", phone=None)
    db.add(guest); db.flush()
    db.add(GuestIdentity(
        tenant_id=tenant_id, guest_id=guest.id,
        identity_type=IdentityType.INSTAGRAM_USER_ID.value, identity_value=igsid,
        confidence=0.9, first_seen_at=None,
    ))
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.INSTAGRAM, is_open=True)
    db.add(conv); db.flush()
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
        direction="outbound", channel=ChannelType.INSTAGRAM, body="Hi",
        delivery_state=MessageDeliveryState.QUEUED,
    )
    db.add(msg); db.commit()
    return guest, conv, msg


def _make_integration(db, tenant_id, ig_account_id="ig-account-1", access_token="real-token"):
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status="active",
        config={"instagram_business_account_id": ig_account_id},
        credentials_kms_blob=encrypt_credentials({"access_token": access_token}),
    )
    db.add(integ); db.commit()
    return integ


def _delivery_state_and_error(db, message_id: str) -> tuple[str, "str | None"]:
    """The task closes/rolls back its own SessionLocal() during error
    handling -- since SessionLocal is patched to the shared test `db`,
    that detaches identity-mapped instances (same quirk documented in
    test_sync_wa_templates.py). Raw SQL, keyed on an id captured before
    the task ran, sidesteps it entirely."""
    row = db.execute(
        text("SELECT delivery_state, delivery_error FROM messages WHERE id = :id"),
        {"id": message_id},
    ).first()
    return row[0], row[1]


def _http_error(status_code: int, json_body: dict | None = None, text: str = ""):
    request = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.text = text or str(json_body)
    response.json.return_value = json_body or {}
    return httpx.HTTPStatusError("error", request=request, response=response)


class TestOutsideMessagingWindow:
    def test_window_closed_error_marks_failed_without_retry(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        guest, conv, msg = _make_conversation_with_pending_message(db, tenant_id)
        msg_id = msg.id

        window_error = _http_error(403, {
            "error": {"message": "(#10) This message is sent outside of allowed window",
                      "type": "OAuthException", "code": 10, "error_subcode": 2018278},
        })

        with patch("app.workers.tasks.send_instagram_dm.SessionLocal", return_value=db), \
             patch("httpx.post", side_effect=window_error):
            result = send_instagram_dm.run(message_id=msg_id, tenant_id=tenant_id)

        assert result["reason"] == "outside_24h_window"
        delivery_state, delivery_error = _delivery_state_and_error(db, msg_id)
        assert delivery_state == MessageDeliveryState.FAILED.value
        assert "24 hours" in delivery_error
        assert "guest hasn't messaged" in delivery_error.lower()

    def test_window_closed_detected_by_message_text_when_subcode_missing(self, db, tenant_and_user):
        """Instagram's Graph API variant isn't confirmed to always carry the
        Messenger-documented subcode -- the message-text match is the
        verified-against-this-incident fallback."""
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        guest, conv, msg = _make_conversation_with_pending_message(db, tenant_id)
        msg_id = msg.id

        window_error = _http_error(403, {
            "error": {"message": "Message is sent outside of allowed window", "type": "OAuthException", "code": 10},
        })

        with patch("app.workers.tasks.send_instagram_dm.SessionLocal", return_value=db), \
             patch("httpx.post", side_effect=window_error):
            result = send_instagram_dm.run(message_id=msg_id, tenant_id=tenant_id)

        assert result["reason"] == "outside_24h_window"

    def test_unrelated_403_still_retries_normally(self, db, tenant_and_user):
        """A genuinely dead/invalid token must not be misclassified as a
        window-closed rejection -- it should still go through the normal
        retry path."""
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        guest, conv, msg = _make_conversation_with_pending_message(db, tenant_id)
        msg_id = msg.id

        auth_error = _http_error(403, {
            "error": {"message": "Error validating access token", "type": "OAuthException", "code": 190},
        })

        with patch("app.workers.tasks.send_instagram_dm.SessionLocal", return_value=db), \
             patch("httpx.post", side_effect=auth_error):
            # bind=True task's self.retry() raising is exactly the point:
            # it proves this exception took the pre-existing retry path,
            # not the new outside-window short-circuit (which returns a
            # dict and never raises).
            with pytest.raises(Exception):
                send_instagram_dm.run(message_id=msg_id, tenant_id=tenant_id)


# ── Replies to Instagram comments go out as private replies ──────────────────
# Confirmed live on Ratha: every failed AI reply over 2 days answered a guest
# who had only COMMENTED on a post. A plain DM to such a person is rejected
# by Meta as "outside of allowed window"; it has to be a private reply tied
# to the comment (once per comment, within 7 days).

from datetime import datetime, timedelta, timezone  # noqa: E402


def _add_inbound(db, conv, *, comment_id=None, age=timedelta(minutes=1)):
    meta = {"source": "comment", "comment_id": comment_id, "media_id": "m1"} if comment_id else {"source": "dm"}
    m = Message(
        id=str(uuid.uuid4()), tenant_id=conv.tenant_id, conversation_id=conv.id,
        direction="inbound", channel=ChannelType.INSTAGRAM, body="Bhadra.",
        channel_metadata=meta, created_at=datetime.now(timezone.utc) - age,
    )
    db.add(m); db.commit()
    return m


def _ok_response(mid="mid.1"):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"message_id": mid}
    return resp


def _run(db, tenant_id, msg_id):
    with patch("app.workers.tasks.send_instagram_dm.SessionLocal", return_value=db), \
         patch("app.workers.tasks.send_instagram_dm.instagram_mark_seen") as seen, \
         patch("httpx.post", return_value=_ok_response()) as post:
        seen.delay = MagicMock()
        result = send_instagram_dm.run(message_id=msg_id, tenant_id=tenant_id)
    return result, post


class TestCommentPrivateReply:
    def test_reply_to_comment_uses_private_reply(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        guest, conv, msg = _make_conversation_with_pending_message(db, tenant_id)
        _add_inbound(db, conv, comment_id="c-777")
        msg_id = msg.id

        result, post = _run(db, tenant_id, msg_id)

        assert result["status"] == "sent"
        body = post.call_args.kwargs.get("json") or post.call_args.args[1]
        assert body["recipient"] == {"comment_id": "c-777"}
        meta = db.execute(text("SELECT channel_metadata FROM messages WHERE id = :id"), {"id": msg_id}).scalar()
        assert "c-777" in str(meta)

    def test_reply_to_dm_still_uses_normal_dm(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        guest, conv, msg = _make_conversation_with_pending_message(db, tenant_id, igsid="ig-dm-9")
        _add_inbound(db, conv)
        result, post = _run(db, tenant_id, msg.id)
        assert result["status"] == "sent"
        body = post.call_args.kwargs.get("json") or post.call_args.args[1]
        assert body["recipient"] == {"id": "ig-dm-9"}

    def test_second_reply_to_same_comment_is_blocked_clearly(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        guest, conv, msg = _make_conversation_with_pending_message(db, tenant_id)
        _add_inbound(db, conv, comment_id="c-888")
        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
            direction="outbound", channel=ChannelType.INSTAGRAM, body="first answer",
            delivery_state=MessageDeliveryState.SENT,
            channel_metadata={"private_reply_comment_id": "c-888"},
        ))
        db.commit()
        msg_id = msg.id

        result, post = _run(db, tenant_id, msg_id)

        assert result["reason"] == "comment_reply_blocked"
        post.assert_not_called()
        state, error = _delivery_state_and_error(db, msg_id)
        assert state == MessageDeliveryState.FAILED.value
        assert "one reply per comment" in error

    def test_comment_older_than_7_days_is_blocked(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        guest, conv, msg = _make_conversation_with_pending_message(db, tenant_id)
        _add_inbound(db, conv, comment_id="c-old", age=timedelta(days=8))
        msg_id = msg.id

        result, post = _run(db, tenant_id, msg_id)

        assert result["reason"] == "comment_reply_blocked"
        post.assert_not_called()
        assert "over 7 days" in _delivery_state_and_error(db, msg_id)[1]
