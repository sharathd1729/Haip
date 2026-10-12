"""
B14 — Celery chain retry + DLQ tests.

Tests that:
  1. Transient failure → task is retried
  2. Permanent failure after max retries → pushed to DLQ
  3. Transcription fallback chain: Groq failure → Deepgram fallback → success
  4. Idempotency: re-running a completed task does not duplicate data
"""

import json
import uuid
import pytest
from unittest.mock import patch, MagicMock, call


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _private_app():
    """An isolated, eager Celery app.

    These tests exercise the retry policy and the DLQ signal, not any production task. Tasks must
    not leak into the shared ``celery_app``: an unrouted test task falls into the unconsumed
    ``celery`` queue and fails ``test_celery_task_routing`` for the whole suite. ``shared=False``
    and ``set_as_current=False`` keep these tasks on this private app only.
    """
    from celery import Celery
    app = Celery(f"retry-test-{uuid.uuid4().hex[:6]}", set_as_current=False)
    app.conf.update(task_always_eager=True, task_eager_propagates=False, task_store_eager_result=False)
    return app


# ─── Test: retry on transient failure ─────────────────────────────────────────

def test_transient_failure_triggers_retry():
    """A task built with the standard retry policy retries a transient error and then succeeds."""
    from app.workers.retry_policy import task_with_retry

    app = _private_app()
    calls = {"n": 0}

    @app.task(shared=False, **task_with_retry(f"test_retry_{uuid.uuid4().hex[:6]}", max_retries=3, countdown=0))
    def flaky(self):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("transient")
        return "ok"

    result = flaky.apply()

    assert calls["n"] == 2, "one failure then one success"
    assert result.result == "ok"


def test_non_transient_error_is_not_retried(monkeypatch):
    """Data/logic errors (e.g. ValueError) fail immediately instead of looping through retries."""
    from app.workers.retry_policy import task_with_retry

    # A final failure reaches the DLQ signal; keep it away from any real Redis.
    monkeypatch.setattr("app.workers.retry_policy.push_to_dlq", lambda *a, **k: None)

    app = _private_app()
    calls = {"n": 0}

    @app.task(shared=False, **task_with_retry(f"test_noretry_{uuid.uuid4().hex[:6]}", max_retries=3, countdown=0))
    def broken(self):
        calls["n"] += 1
        raise ValueError("bad input")

    broken.apply()

    assert calls["n"] == 1


# ─── Test: DLQ push on exhausted retries ──────────────────────────────────────

def test_dlq_push_on_exhausted_retries(monkeypatch):
    """A task that keeps failing is pushed to the DLQ exactly once, after its retries run out."""
    from app.workers.retry_policy import task_with_retry

    pushed = []
    monkeypatch.setattr(
        "app.workers.retry_policy.push_to_dlq",
        lambda task_name, task_id, args, kwargs, exc: pushed.append((task_name, task_id, repr(exc))),
    )

    app = _private_app()
    calls = {"n": 0}
    name = f"test_dlq_{uuid.uuid4().hex[:6]}"

    @app.task(shared=False, **task_with_retry(name, max_retries=2, countdown=0))
    def always_down(self):
        calls["n"] += 1
        raise ConnectionError("provider down")

    always_down.apply()

    assert calls["n"] == 3, "first attempt plus two retries"
    assert len(pushed) == 1, f"expected a single DLQ entry, got {pushed}"
    assert pushed[0][0] == name
    assert "ConnectionError" in pushed[0][2]


# ─── Test: transcription provider selection ───────────────────────────────────

@pytest.mark.parametrize("provider,module,cls", [
    ("sarvam", "app.adapters.transcription.sarvam", "SarvamAdapter"),
    ("groq", "app.adapters.transcription.groq_whisper", "GroqWhisperAdapter"),
    ("deepgram", "app.adapters.transcription.deepgram", "DeepgramAdapter"),
    ("whisper", "app.adapters.transcription.whisper", "WhisperAdapter"),
])
def test_transcription_factory_returns_the_requested_provider(provider, module, cls):
    """The factory maps each provider name to its adapter class.

    NOTE: there is no runtime failover between providers. ``get_transcription_adapter`` picks one
    adapter and the ``transcribe`` task only retries that same adapter. The Sarvam -> Deepgram ->
    Whisper chain in CLAUDE.md is selection-by-config, not automatic fallback (see
    docs/HAIP_Phase0_Failure_Register.md). The previous test of this name ran its own loop over
    mocks and proved nothing about the application.
    """
    import importlib
    from app.adapters.transcription import get_transcription_adapter

    adapter = get_transcription_adapter(provider)
    assert isinstance(adapter, getattr(importlib.import_module(module), cls))


def test_transcription_factory_auto_detects_by_available_key(monkeypatch):
    from app.adapters.transcription import _auto_detect_transcription
    from app.core.config import settings

    for key in ("SARVAM_API_KEY", "GROQ_API_KEY", "DEEPGRAM_API_KEY"):
        monkeypatch.setattr(settings, key, "")
    assert _auto_detect_transcription() == "whisper"
    monkeypatch.setattr(settings, "DEEPGRAM_API_KEY", "x")
    assert _auto_detect_transcription() == "deepgram"
    monkeypatch.setattr(settings, "GROQ_API_KEY", "x")
    assert _auto_detect_transcription() == "groq"
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "x")
    assert _auto_detect_transcription() == "sarvam"


# ─── Test: DLQ storage format ─────────────────────────────────────────────────

def test_dlq_storage_format():
    """Verify push_to_dlq stores a correctly-formatted JSON entry."""
    from app.workers.retry_policy import push_to_dlq
    import redis as _redis
    from app.core.config import settings

    try:
        r = _redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
    except Exception:
        pytest.skip("Redis not available for integration test")

    task_name = f"test.dlq.format.{uuid.uuid4().hex[:6]}"
    task_id = str(uuid.uuid4())
    key = f"dlq:{task_name}"

    # Clean up before
    r.delete(key)

    push_to_dlq(task_name, task_id, ["arg1"], {"key": "val"}, ValueError("test error"))

    raw = r.lrange(key, 0, 0)
    assert len(raw) == 1
    entry = json.loads(raw[0])
    assert entry["task_name"] == task_name
    assert entry["task_id"] == task_id
    assert "ValueError" in entry["error"]
    assert "failed_at" in entry

    # Clean up
    r.delete(key)


# ─── Test: task idempotency ───────────────────────────────────────────────────

def test_whatsapp_message_idempotency(db, client, monkeypatch):
    """
    Processing the same WhatsApp message twice should not create duplicate rows.
    Tests the channel_message_id dedup check.
    """
    import uuid as _uuid
    from app.models.conversation import Message
    from app.models.tenant import Tenant
    from app.workers.tasks.whatsapp import _handle_inbound_message

    # Create tenant
    t = Tenant(id=str(_uuid.uuid4()), name="Idem Hotel",
               slug=f"idem-{_uuid.uuid4().hex[:6]}",
               whatsapp_phone_number_id="idem_pn")
    db.add(t)
    db.commit()

    wa_id = f"wamid.idem_{_uuid.uuid4().hex[:8]}"
    msg = {
        "from": "919876543210",
        "id": wa_id,
        "type": "text",
        "text": {"body": "Idempotent message"},
        "timestamp": "1700000000",
    }
    contacts = [{"wa_id": "919876543210", "profile": {"name": "Idem Guest"}}]

    # Call twice — should only store one message
    monkeypatch.setattr("app.workers.tasks.concierge_draft.concierge_draft.apply_async",
                        lambda *a, **k: None)
    _handle_inbound_message(db, t, msg, contacts)
    db.commit()
    _handle_inbound_message(db, t, msg, contacts)
    db.commit()

    count = db.query(Message).filter_by(channel_message_id=wa_id).count()
    assert count == 1, "Duplicate wa_id should not create duplicate Message"
