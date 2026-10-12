"""
Tests for B3: conversation list + message thread pagination.

Covers:
- GET /conversations?before=... cursor pagination (load more, no overlap)
- GET /conversations/{id} returns the MOST RECENT N messages, not the oldest
  N (previously .order_by(asc).limit(200) showed the oldest 200 for any
  thread over 200 messages -- backwards for a chat UI)
- GET /conversations/{id}/messages?before=... "load older" cursor pagination
- Malformed `before` cursor on either endpoint -> 422
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.guest import Guest
from app.models.conversation import Conversation, Message


@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


@pytest.fixture()
def guest(db, tenant_and_user):
    g = Guest(
        id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id,
        phone="+919999000002", name="Pagination Test Guest",
    )
    db.add(g); db.flush(); db.commit()
    return g


def _make_conversation(db, tenant_id, guest_id, last_message_at: str):
    """One open conversation per guest and channel is a database rule (migration 099), so a test that needs several
    open WhatsApp conversations in a tenant gives each its own guest; the first one uses `guest_id`."""
    taken = db.query(Conversation.id).filter_by(
        tenant_id=tenant_id, guest_id=guest_id, channel="whatsapp", is_open=True).first()
    if taken is not None:
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone=f"+9199{uuid.uuid4().int % 10**8:08d}", name="Another Guest")
        db.add(guest)
        db.flush()
        guest_id = guest.id
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        channel="whatsapp", is_open=True, last_message_at=last_message_at,
    )
    db.add(conv)
    db.flush()          # sessions run with autoflush off; make this conversation visible to the next call
    return conv


def _make_message(db, tenant_id, conversation_id, created_at: datetime, body: str, direction="inbound"):
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation_id,
        direction=direction, channel="whatsapp", body=body, created_at=created_at,
    )
    db.add(msg)
    return msg


# ── Conversation list cursor pagination ────────────────────────────────────────

class TestConversationListPagination:
    def test_before_cursor_excludes_newer_conversations(self, client, db, auth_headers, tenant_and_user, guest):
        tenant_id = tenant_and_user["tenant"].id
        now = datetime.now(timezone.utc)
        # Three conversations, staggered by an hour each.
        c_oldest = _make_conversation(db, tenant_id, guest.id, (now - timedelta(hours=2)).isoformat())
        c_mid = _make_conversation(db, tenant_id, guest.id, (now - timedelta(hours=1)).isoformat())
        c_newest = _make_conversation(db, tenant_id, guest.id, now.isoformat())
        db.commit()

        client.headers.update(auth_headers)

        # First page: no cursor, most recent first.
        r1 = client.get("/api/v1/conversations", params={"limit": 2})
        assert r1.status_code == 200
        page1_ids = [c["id"] for c in r1.json()]
        assert page1_ids == [c_newest.id, c_mid.id]

        # Next page: cursor on the oldest item from page 1.
        r2 = client.get("/api/v1/conversations", params={"limit": 2, "before": c_mid.last_message_at})
        assert r2.status_code == 200
        page2_ids = [c["id"] for c in r2.json()]
        assert page2_ids == [c_oldest.id]
        # No overlap between pages.
        assert not (set(page1_ids) & set(page2_ids))

    def test_malformed_before_cursor_returns_422(self, client, auth_headers, tenant_and_user):
        client.headers.update(auth_headers)
        resp = client.get("/api/v1/conversations", params={"before": "not-a-timestamp"})
        assert resp.status_code == 422


class TestPersonalBridgeSourceFiltering:
    """Personal WhatsApp bridge conversations (source="personal_bridge")
    share channel="whatsapp" with the official Cloud API but are kept out
    of the main Inbox for now (product decision) -- excluded from every
    list unless source is explicitly requested."""

    def test_personal_bridge_conversation_excluded_by_default(self, client, db, auth_headers, tenant_and_user, guest):
        tenant_id = tenant_and_user["tenant"].id
        now = datetime.now(timezone.utc).isoformat()
        official = _make_conversation(db, tenant_id, guest.id, now)
        bridged = _make_conversation(db, tenant_id, guest.id, now)
        bridged.source = "personal_bridge"
        db.commit()

        client.headers.update(auth_headers)
        resp = client.get("/api/v1/conversations")
        ids = [c["id"] for c in resp.json()]
        assert official.id in ids
        assert bridged.id not in ids

        # The "WhatsApp" channel tab must not leak it in either.
        resp_ch = client.get("/api/v1/conversations", params={"channel": "whatsapp"})
        ch_ids = [c["id"] for c in resp_ch.json()]
        assert bridged.id not in ch_ids

    def test_explicit_source_param_returns_only_bridged(self, client, db, auth_headers, tenant_and_user, guest):
        tenant_id = tenant_and_user["tenant"].id
        now = datetime.now(timezone.utc).isoformat()
        official = _make_conversation(db, tenant_id, guest.id, now)
        bridged = _make_conversation(db, tenant_id, guest.id, now)
        bridged.source = "personal_bridge"
        db.commit()

        client.headers.update(auth_headers)
        resp = client.get("/api/v1/conversations", params={"source": "personal_bridge"})
        ids = [c["id"] for c in resp.json()]
        assert ids == [bridged.id]
        assert official.id not in ids


# ── Conversation detail: most recent messages, not oldest ──────────────────────

class TestConversationDetailMessageOrdering:
    def test_returns_most_recent_messages_when_over_cap(self, client, db, auth_headers, tenant_and_user, guest):
        tenant_id = tenant_and_user["tenant"].id
        conv = _make_conversation(db, tenant_id, guest.id, datetime.now(timezone.utc).isoformat())
        db.flush()

        # 60 messages, 1 minute apart -- comfortably over a small test cap
        # but this endpoint's real cap is 50, so create 55 to cross it.
        base = datetime.now(timezone.utc) - timedelta(minutes=55)
        for i in range(55):
            _make_message(db, tenant_id, conv.id, base + timedelta(minutes=i), f"msg-{i}")
        db.commit()

        client.headers.update(auth_headers)
        resp = client.get(f"/api/v1/conversations/{conv.id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_messages"] == 55
        assert data["messages_capped"] is True
        assert len(data["messages"]) == 50
        # Must be the most recent 50 (msg-5 .. msg-54), not the oldest 50
        # (msg-0 .. msg-49) -- and still in chronological (ascending) order
        # for display.
        texts = [m["text"] for m in data["messages"]]
        assert texts[0] == "msg-5"
        assert texts[-1] == "msg-54"
        assert texts == sorted(texts, key=lambda t: int(t.split("-")[1]))

    def test_not_capped_when_under_limit(self, client, db, auth_headers, tenant_and_user, guest):
        tenant_id = tenant_and_user["tenant"].id
        conv = _make_conversation(db, tenant_id, guest.id, datetime.now(timezone.utc).isoformat())
        db.flush()
        _make_message(db, tenant_id, conv.id, datetime.now(timezone.utc), "only-message")
        db.commit()

        client.headers.update(auth_headers)
        resp = client.get(f"/api/v1/conversations/{conv.id}")
        data = resp.json()
        assert data["total_messages"] == 1
        assert data["messages_capped"] is False


# ── "Load older" cursor pagination on GET /{id}/messages ───────────────────────

class TestLoadOlderMessages:
    def test_before_cursor_loads_strictly_older_messages(self, client, db, auth_headers, tenant_and_user, guest):
        tenant_id = tenant_and_user["tenant"].id
        conv = _make_conversation(db, tenant_id, guest.id, datetime.now(timezone.utc).isoformat())
        db.flush()

        base = datetime.now(timezone.utc) - timedelta(minutes=10)
        msgs = [_make_message(db, tenant_id, conv.id, base + timedelta(minutes=i), f"m{i}") for i in range(5)]
        db.commit()

        client.headers.update(auth_headers)

        # Load the 2 most recent via the cursor endpoint directly.
        r1 = client.get(f"/api/v1/conversations/{conv.id}/messages", params={"limit": 2})
        assert r1.status_code == 200
        page1 = r1.json()
        assert [m["text"] for m in page1["messages"]] == ["m3", "m4"]
        assert page1["has_more"] is True

        # Load older than the earliest one we have.
        cursor = page1["messages"][0]["timestamp"]
        r2 = client.get(f"/api/v1/conversations/{conv.id}/messages", params={"limit": 2, "before": cursor})
        assert r2.status_code == 200
        page2 = r2.json()
        assert [m["text"] for m in page2["messages"]] == ["m1", "m2"]

    def test_has_more_false_at_end_of_history(self, client, db, auth_headers, tenant_and_user, guest):
        tenant_id = tenant_and_user["tenant"].id
        conv = _make_conversation(db, tenant_id, guest.id, datetime.now(timezone.utc).isoformat())
        db.flush()
        _make_message(db, tenant_id, conv.id, datetime.now(timezone.utc), "only")
        db.commit()

        client.headers.update(auth_headers)
        resp = client.get(f"/api/v1/conversations/{conv.id}/messages", params={"limit": 50})
        data = resp.json()
        assert data["has_more"] is False

    def test_malformed_before_cursor_returns_422(self, client, db, auth_headers, tenant_and_user, guest):
        tenant_id = tenant_and_user["tenant"].id
        conv = _make_conversation(db, tenant_id, guest.id, datetime.now(timezone.utc).isoformat())
        db.commit()

        client.headers.update(auth_headers)
        resp = client.get(f"/api/v1/conversations/{conv.id}/messages", params={"before": "garbage"})
        assert resp.status_code == 422

    def test_cross_tenant_conversation_returns_404(self, client, db, auth_headers, tenant_and_user):
        """A different tenant's conversation must not be reachable, even via the messages sub-route."""
        import uuid as _uuid
        from app.models.tenant import Tenant
        other_tenant = Tenant(id=str(_uuid.uuid4()), name="Other", slug=f"other-{_uuid.uuid4().hex[:6]}", plan="growth")
        db.add(other_tenant); db.flush()
        other_guest = Guest(id=str(_uuid.uuid4()), tenant_id=other_tenant.id, phone="+919999000003", name="Other Guest")
        db.add(other_guest); db.flush()
        other_conv = _make_conversation(db, other_tenant.id, other_guest.id, datetime.now(timezone.utc).isoformat())
        db.commit()

        client.headers.update(auth_headers)
        resp = client.get(f"/api/v1/conversations/{other_conv.id}/messages")
        assert resp.status_code == 404
