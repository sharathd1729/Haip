"""Tests for the message-burst debounce: a guest sending 2+ messages a few
seconds apart must produce exactly 1 AI draft, grounded on the whole burst --
not one disjointed draft per message. See concierge_service.py's
DEBOUNCE_SECONDS / mark_pending_draft / is_latest_pending_draft, and
concierge_draft.py's staleness check at the top of the task.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType
from app.services import concierge_service
from app.services.concierge_service import (
    mark_pending_draft, is_latest_pending_draft, unanswered_guest_text,
)
from app.workers.tasks.concierge_draft import concierge_draft


@pytest.fixture
def fake_cache(monkeypatch):
    """In-memory stand-in for Redis so the debounce gate is deterministic in
    CI regardless of whether a real Redis is reachable (get_cached/set_cached
    fail open to None on a Redis outage, which would make the superseded
    check always pass -- the opposite of what this test needs to prove)."""
    store: dict = {}

    def _get(key):
        return store.get(key)

    def _set(key, value, ttl=300):
        store[key] = value

    monkeypatch.setattr(concierge_service, "get_cached", _get)
    monkeypatch.setattr(concierge_service, "set_cached", _set)
    return store


class TestDebounceGate:
    def test_is_latest_pending_draft_true_for_only_message(self, fake_cache):
        mark_pending_draft("t1", "c1", "m1")
        assert is_latest_pending_draft("t1", "c1", "m1") is True

    def test_superseded_by_newer_message_returns_false(self, fake_cache):
        mark_pending_draft("t1", "c1", "m1")
        mark_pending_draft("t1", "c1", "m2")
        assert is_latest_pending_draft("t1", "c1", "m1") is False
        assert is_latest_pending_draft("t1", "c1", "m2") is True

    def test_no_pending_key_fails_open(self, fake_cache):
        # Cache miss (never marked, or Redis down) -- must not silently drop
        # the guest's reply.
        assert is_latest_pending_draft("t1", "c1", "m1") is True

    def test_scoped_per_conversation(self, fake_cache):
        mark_pending_draft("t1", "c1", "m1")
        mark_pending_draft("t1", "c2", "m2")
        assert is_latest_pending_draft("t1", "c1", "m1") is True
        assert is_latest_pending_draft("t1", "c2", "m2") is True


def _setup_conversation(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919876500002", name="Rahul")
    db.add(guest); db.commit()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True, ai_mode="shadow")
    db.add(conv); db.commit()
    return tenant, guest, conv


def _add_inbound(db, tenant, conv, body, at=None):
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel="whatsapp", body=body,
        **({"created_at": at} if at else {}),
    )
    db.add(msg); db.commit()
    return msg


class TestUnansweredGuestText:
    def test_combines_burst_into_one_query(self, db):
        tenant, guest, conv = _setup_conversation(db)
        _add_inbound(db, tenant, conv, "Hi")
        _add_inbound(db, tenant, conv, "I want to book this weekend")

        text = unanswered_guest_text(db, tenant.id, conv.id)
        assert text == "Hi\nI want to book this weekend"

    def test_only_messages_since_last_outbound(self, db):
        tenant, guest, conv = _setup_conversation(db)
        base = datetime.now(timezone.utc)
        _add_inbound(db, tenant, conv, "old message", at=base)
        outbound = Message(
            id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
            direction="outbound", channel="whatsapp", body="How can I help?",
            created_at=base + timedelta(seconds=1),
        )
        db.add(outbound); db.commit()
        _add_inbound(db, tenant, conv, "Hi", at=base + timedelta(seconds=2))
        _add_inbound(db, tenant, conv, "I want to book this weekend", at=base + timedelta(seconds=3))

        text = unanswered_guest_text(db, tenant.id, conv.id)
        assert "old message" not in text
        assert text == "Hi\nI want to book this weekend"


class TestConciergeDraftBurstEndToEnd:
    def test_burst_of_two_messages_produces_exactly_one_draft(self, db, monkeypatch, fake_cache):
        tenant, guest, conv = _setup_conversation(db)
        msg1 = _add_inbound(db, tenant, conv, "Hi")
        msg2 = _add_inbound(db, tenant, conv, "I want to book this weekend")

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {
                    "reply": "Happy to help you plan your weekend! What dates work for you?",
                    "confidence": 0.6, "citations": [], "needs_human": False,
                }}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)

        # Mirrors whatsapp.py's/process_instagram_dm.py's dispatch: each
        # inbound message marks itself as the latest pending draft before
        # queuing its own (fresh-delay) concierge_draft run.
        mark_pending_draft(tenant.id, conv.id, msg1.id)
        mark_pending_draft(tenant.id, conv.id, msg2.id)

        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"):
            # msg1's task fires first (it was queued first) -- by now msg2
            # has superseded it, so this must no-op, not draft a reply to
            # "Hi" alone.
            concierge_draft.run(message_id=msg1.id, conversation_id=conv.id, tenant_id=tenant.id)
            drafts_after_first = (
                db.query(Message)
                .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
                .all()
            )
            assert len(drafts_after_first) == 0

            # msg2's task fires next -- still latest, drafts once, grounded
            # on the whole unanswered burst.
            concierge_draft.run(message_id=msg2.id, conversation_id=conv.id, tenant_id=tenant.id)

        drafts = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
            .all()
        )
        assert len(drafts) == 1
        assert drafts[0].ai_intent == "general"


class TestConciergeDraftSupersededBeforeSend:
    def test_second_message_arriving_mid_draft_blocks_the_autonomous_send(self, db, monkeypatch, fake_cache):
        """Regression: a burst message arriving more than DEBOUNCE_SECONDS
        after the first doesn't overwrite the pending-draft key until AFTER
        the first task's entry-time staleness check already passed -- that
        task then has no way to know it's been superseded unless it checks
        again before the one irreversible step, the send. Confirmed live:
        two guest messages 6s apart (just past DEBOUNCE_SECONDS=5) each
        independently passed their own entry check and both auto-sent,
        producing a duplicate guest-facing reply and burning an extra
        rate-limit slot that went on to block a later, real question from
        auto-sending."""
        tenant, guest, conv = _setup_conversation(db)
        tenant.wa_ai_mode_default = "autonomous"
        tenant.wa_ai_confidence_threshold = 0.5
        db.commit()

        msg1 = _add_inbound(db, tenant, conv, "What services do you offer?")

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                # Simulate msg2 arriving while this (slow) completion was in
                # flight -- exactly the observed live race: dispatch marks
                # msg2 as the new latest pending draft partway through msg1's
                # task, well after msg1's own entry-time check already passed.
                msg2 = _add_inbound(db, tenant, conv, "How much do your services cost?")
                mark_pending_draft(tenant.id, conv.id, msg2.id)
                return {"tool_use": {
                    "reply": "We offer luxury caravan travel experiences.",
                    "confidence": 0.95, "citations": [], "needs_human": False,
                }}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)
        mark_pending_draft(tenant.id, conv.id, msg1.id)

        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"), \
             patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as mock_send:
            concierge_draft.run(message_id=msg1.id, conversation_id=conv.id, tenant_id=tenant.id)

        mock_send.assert_not_called()
        draft = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
            .first()
        )
        assert draft is not None
        assert draft.sent_autonomously is False
        assert "superseded" in (draft.ai_needs_human_reason or "")
