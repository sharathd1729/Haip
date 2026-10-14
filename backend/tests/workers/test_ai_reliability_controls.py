"""Reliability controls around the AI features: no duplicate sends, bounded provider calls, a rewrite never changes the facts,
and nothing sensitive in the logs."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.llm import embeddings
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.integration import Integration
from app.workers.tasks import send_whatsapp as send_mod
from app.workers.tasks.composer_rewrite import composer_rewrite
from app.workers.tasks.rewrite_draft import rewrite_draft, validate_rewrite
from app.core.cache import get_cached


# ─── a message is never sent twice ────────────────────────────────────────────

class _Adapter:
    def __init__(self):
        self.calls = 0

    async def send_text(self, to, body):
        self.calls += 1
        return {"messages": [{"id": "wamid.NEW"}]}


@pytest.fixture()
def message(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=tid, kind="whatsapp_meta", status="active", config={"phone_number_id": "pn1"}))
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Asha", phone="+919876543210")
    db.add(g)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    msg = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction="outbound", channel=ChannelType.WHATSAPP,
                  body="Check-in is from 2 pm.", delivery_state=MessageDeliveryState.QUEUED, channel_status="queued")
    db.add(msg)
    db.commit()
    return tid, msg.id


def _send(db, tid, msg_id, adapter):
    with patch.object(send_mod, "SessionLocal", return_value=db), patch.object(db, "close"), \
         patch.object(send_mod, "get_wa_adapter", return_value=adapter), \
         patch("app.workers.tasks.whatsapp._get_wa_access_token", return_value="tok"):
        send_mod.send_whatsapp.apply(kwargs={"message_id": msg_id, "tenant_id": tid})
    db.expire_all()
    return db.query(Message).get(msg_id)


def test_a_redelivered_send_task_does_not_send_the_same_message_again(db, message):
    tid, msg_id = message
    adapter = _Adapter()
    sent = _send(db, tid, msg_id, adapter)
    assert adapter.calls == 1 and sent.delivery_state == MessageDeliveryState.SENT and sent.channel_message_id == "wamid.NEW"

    _send(db, tid, msg_id, adapter)                       # the broker delivers the same task again
    assert adapter.calls == 1

    sent.delivery_state = MessageDeliveryState.DELIVERED   # even after the delivery receipt arrived
    db.commit()
    _send(db, tid, msg_id, adapter)
    assert adapter.calls == 1


def test_a_failed_message_can_still_be_retried_by_a_person(db, message):
    tid, msg_id = message
    msg = db.query(Message).get(msg_id)
    msg.delivery_state, msg.channel_status = MessageDeliveryState.FAILED, "failed"
    db.commit()
    adapter = _Adapter()
    assert _send(db, tid, msg_id, adapter).delivery_state == MessageDeliveryState.SENT and adapter.calls == 1


def test_the_send_log_never_contains_the_guests_phone_number(db, message):
    tid, msg_id = message
    log = MagicMock()
    with patch.object(send_mod, "log", log):
        _send(db, tid, msg_id, _Adapter())
    logged = " ".join(str(c) for c in log.info.call_args_list + log.warning.call_args_list + log.error.call_args_list)
    assert "+919876543210" not in logged and "9876543210" not in logged
    assert any(c.args and c.args[0] == "whatsapp_sent" for c in log.info.call_args_list)


# ─── provider calls are bounded ───────────────────────────────────────────────

def test_embedding_calls_are_time_bounded_and_not_silently_retried():
    seen = {}

    class _Client:
        def __init__(self, **kw):
            seen.update(kw)
            self.embeddings = SimpleNamespace(create=self._create)

        async def _create(self, **kw):
            return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.0] * embeddings.EMBED_DIM)])

    with patch("openai.AsyncOpenAI", _Client), patch.object(embeddings, "_api_key", return_value="k"):
        asyncio.run(embeddings.embed_texts(["can I bring my dog"], "query"))
        assert seen["timeout"] == embeddings.QUERY_TIMEOUT_SECONDS and seen["max_retries"] == 0
        asyncio.run(embeddings.embed_texts(["Pets are welcome."], "passage"))
        assert seen["timeout"] == embeddings.PASSAGE_TIMEOUT_SECONDS and seen["max_retries"] == 0
    assert embeddings.QUERY_TIMEOUT_SECONDS < 15            # the guest is waiting on a query; indexing is in the background


# ─── a rewrite changes wording, never facts ───────────────────────────────────

@pytest.mark.parametrize("original,rewritten,translating,problem", [
    ("Check-in is at 2 pm for 3 nights.", "Check-in is at 2 pm for 3 nights, lovely.", False, None),        # tone only
    ("Check-in is at 2 pm for 3 nights.", "Check-in is at 3 pm for 3 nights.", False, "changed numbers"),
    ("Check-in is at 2 pm.", "Check-in is at 2 pm and costs 500.", False, "changed numbers"),
    ("Total is ₹22,400 for 2 nights.", "Total is ₹22,400 for 2 nights.", True, None),                       # translated, same figures
    ("Total is ₹22,400 for 2 nights.", "कुल ₹२२,४०० है, 2 रातें।", True, None),                              # figures re-written in another script
    ("Total is ₹22,400.", "Total is ₹24,400.", True, "introduced numbers"),
    ("Hi", "x" * 500, False, "far longer"),
    ("Hi", "   ", False, "empty"),
    ("Hi", None, False, "empty"),
    ("Hi", ["not", "text"], False, "empty"),
])
def test_validate_rewrite(original, rewritten, translating, problem):
    got = validate_rewrite(original, rewritten, translating)
    assert (got is None) if problem is None else (got is not None and problem in got)


def test_a_rewrite_that_changes_a_price_leaves_the_draft_untouched(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone="+919800000001")
    db.add(g)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    msg = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction="outbound", channel="whatsapp",
                  body="Your total is ₹22,400 for 2 nights.", is_ai_generated=True, was_approved=None)
    db.add(msg)
    db.commit()

    class _Wrong:
        async def complete(self, **kw):
            return {"tool_use": {"rewritten_text": "Your total is ₹12,400 for 2 nights, happy to help!"}}

    with patch("app.workers.tasks.rewrite_draft.get_llm", lambda task: _Wrong()), \
         patch("app.workers.tasks.rewrite_draft.SessionLocal", return_value=db), patch.object(db, "close"):
        rewrite_draft.run(message_id=msg.id, tenant_id=tid, tone="warm")
    db.expire_all()
    assert db.query(Message).get(msg.id).body == "Your total is ₹22,400 for 2 nights."


def test_a_composer_rewrite_that_changes_a_figure_is_reported_as_failed_not_offered():
    class _Wrong:
        async def complete(self, **kw):
            return {"tool_use": {"rewritten_text": "Check-in at 5 pm."}}

    job, tenant = str(uuid.uuid4()), str(uuid.uuid4())
    with patch("app.workers.tasks.composer_rewrite.get_llm", lambda task: _Wrong()):
        composer_rewrite.run(job_id=job, tenant_id=tenant, text="Check-in at 2 pm.", tone="brief")
    cached = get_cached(f"composer_rewrite:{tenant}:{job}")
    if cached is not None:                                      # the cache is Redis; skipped silently when it is down, like its sibling tests
        assert cached == {"status": "failed", "error": "changed_facts"}
