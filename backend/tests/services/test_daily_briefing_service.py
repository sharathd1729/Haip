"""Today (Worklist) — AI Daily Briefing.

Covers: an empty worklist never calls the LLM (deterministic "all clear"
message instead); a real worklist calls the LLM and caches a parsed
result; unparseable LLM output returns None and caches nothing; briefing
generation is tenant-isolated via the cache key.
"""
import json
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.services import daily_briefing_service
from app.services.daily_briefing_service import generate_briefing, get_cached_briefing


def _fake_cache(monkeypatch):
    """In-memory stand-in for Redis, same pattern as
    test_concierge_draft_debounce.py's fake_cache -- get_cached/set_cached
    fail open to None on a Redis outage, which would make every "was it
    cached" assertion here vacuously pass."""
    store: dict = {}

    def _get(key):
        return store.get(key)

    def _set(key, value, ttl=300):
        store[key] = value

    monkeypatch.setattr(daily_briefing_service, "get_cached", _get)
    monkeypatch.setattr(daily_briefing_service, "set_cached", _set)
    return store


def _make_tenant(db):
    tenant_id = str(uuid.uuid4())
    db.add(Tenant(id=tenant_id, name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth"))
    db.commit()
    return tenant_id


def _make_awaiting_reply(db, tenant_id):
    """One inbound message with nothing after it -- a real "awaiting_reply"
    row for build_worklist to pick up."""
    guest_id = str(uuid.uuid4())
    db.add(Guest(id=guest_id, tenant_id=tenant_id, name="Priya", phone="+919876500001"))
    conv_id = str(uuid.uuid4())
    db.add(Conversation(id=conv_id, tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP))
    db.add(Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv_id,
        direction=MessageDirection.INBOUND, channel=ChannelType.WHATSAPP,
        body="Is the Nandi Hills route open?",
    ))
    db.commit()


def _fake_adapter(narrative="5 leads waiting.", flags=None):
    payload = {"narrative": narrative, "flags": flags or []}

    class _Fake:
        async def complete(self, **kwargs):
            return {"content": json.dumps(payload), "model": "test-model"}
    return _Fake()


class TestEmptyWorklistSkipsLLM:
    def test_no_rows_returns_deterministic_message_without_calling_llm(self, db, monkeypatch):
        _fake_cache(monkeypatch)
        tenant_id = _make_tenant(db)

        with patch("app.adapters.llm.get_llm") as mock_get_llm:
            result = generate_briefing(db, tenant_id)

        mock_get_llm.assert_not_called()
        assert result["narrative"] == "Nothing outstanding right now — all caught up."
        assert result["flags"] == []
        assert get_cached_briefing(tenant_id) == result


class TestRealWorklistCallsLlm:
    def test_non_empty_worklist_generates_and_caches_parsed_result(self, db, monkeypatch):
        _fake_cache(monkeypatch)
        tenant_id = _make_tenant(db)
        _make_awaiting_reply(db, tenant_id)
        adapter = _fake_adapter(
            narrative="Priya is waiting on a reply about the Nandi Hills route.",
            flags=[{"type": "quick_win", "text": "Answer Priya's route question."}],
        )

        with patch("app.adapters.llm.get_llm", return_value=adapter):
            result = generate_briefing(db, tenant_id)

        assert result is not None
        assert "Priya" in result["narrative"]
        assert result["flags"][0]["type"] == "quick_win"
        assert "generated_at" in result
        assert get_cached_briefing(tenant_id) == result


class TestUnparseableOutputCachesNothing:
    def test_malformed_llm_response_returns_none_and_does_not_cache(self, db, monkeypatch):
        cache = _fake_cache(monkeypatch)
        tenant_id = _make_tenant(db)
        _make_awaiting_reply(db, tenant_id)

        class _BrokenAdapter:
            async def complete(self, **kwargs):
                return {"content": "not json at all", "model": "test-model"}

        with patch("app.adapters.llm.get_llm", return_value=_BrokenAdapter()):
            result = generate_briefing(db, tenant_id)

        assert result is None
        assert get_cached_briefing(tenant_id) is None
        assert cache == {}


class TestTenantIsolation:
    def test_briefing_cache_key_is_scoped_per_tenant(self, db, monkeypatch):
        _fake_cache(monkeypatch)
        tenant_a = _make_tenant(db)
        tenant_b = _make_tenant(db)
        _make_awaiting_reply(db, tenant_a)
        # tenant_b has no rows -- empty-worklist path, no LLM call needed.

        with patch("app.adapters.llm.get_llm", return_value=_fake_adapter(narrative="Tenant A narrative.")):
            generate_briefing(db, tenant_a)
        generate_briefing(db, tenant_b)

        assert "Tenant A" in get_cached_briefing(tenant_a)["narrative"]
        assert get_cached_briefing(tenant_b)["narrative"] == "Nothing outstanding right now — all caught up."
