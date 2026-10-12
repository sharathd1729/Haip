"""The AI-rewrite tasks are bounded: a hung provider cannot hold a worker slot.

Background: the NVIDIA client has no timeout of its own (the openai SDK then waits up to 10 minutes) and the production
worker runs two processes shared by every queue, so two hung rewrite clicks could stall WhatsApp processing. The tasks now
wrap the provider call in asyncio.wait_for (REWRITE_TIMEOUT_SECONDS) and carry Celery time limits as a backstop.

Pinned here: a hung provider ends quickly and exactly one provider request is made; a timeout is never retried; the draft
task retries a plain provider error once (not three times); the composer reports "failed / timeout" through the real
status endpoint; the worst-case durations are what the comments in rewrite_draft.py say. The provider is a fake coroutine,
so no AI service is contacted; the hang is simulated with a long asyncio.sleep and a shortened timeout.
"""
import asyncio
import time
import uuid
from unittest.mock import patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.workers.tasks import composer_rewrite as composer_module
from app.workers.tasks import rewrite_draft as draft_module
from app.workers.tasks.composer_rewrite import composer_rewrite
from app.workers.tasks.rewrite_draft import rewrite_draft

QUICK = 0.2        # the shortened timeout used to simulate a hang without waiting 30 s
MUST_END_BY = 5.0  # generous: proves the task did not wait for the 30 s sleep below


class _HungLLM:
    """Never answers within the timeout."""
    def __init__(self):
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        await asyncio.sleep(30)
        return {"tool_use": {"rewritten_text": "too late"}}


class _BrokenLLM:
    def __init__(self, exc):
        self.calls = 0
        self._exc = exc

    async def complete(self, **kwargs):
        self.calls += 1
        raise self._exc


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _pending_draft(db, tenant_id, body="The villa is free those dates!"):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone=f"+91999{uuid.uuid4().int % 10**7:07d}")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction="outbound", channel="whatsapp",
                  body=body, is_ai_generated=True, was_approved=None)
    db.add(msg); db.commit()
    return conv, msg


@pytest.fixture()
def quick_timeout(monkeypatch):
    monkeypatch.setattr(draft_module, "REWRITE_TIMEOUT_SECONDS", QUICK)


@pytest.fixture()
def cache(monkeypatch):
    """Captures what composer_rewrite writes to the job cache."""
    store = {}
    monkeypatch.setattr(composer_module, "set_cached", lambda key, value, ttl=None: store.__setitem__(key, value))
    return store


# ── the draft task ─────────────────────────────────────────────────────────────────────────────────────────

def test_draft_task_gives_up_on_a_hung_provider_leaves_the_draft_and_never_retries(db, tenant_and_user, quick_timeout):
    tenant_id = _tenant_id(tenant_and_user)
    _, msg = _pending_draft(db, tenant_id)
    msg_id, original = msg.id, msg.body
    llm = _HungLLM()

    started = time.monotonic()
    with patch.object(draft_module, "get_llm", return_value=llm), \
         patch.object(draft_module, "SessionLocal", return_value=db), \
         patch.object(rewrite_draft, "retry", side_effect=AssertionError("a timeout must not be retried")):
        rewrite_draft.run(message_id=msg_id, tenant_id=tenant_id, tone="warm")   # must return, not raise

    assert time.monotonic() - started < MUST_END_BY
    assert llm.calls == 1                                    # one provider request, not four
    assert db.query(Message).filter_by(id=msg_id).first().body == original


def test_draft_task_retries_a_plain_provider_error_exactly_once(db, tenant_and_user):
    tenant_id = _tenant_id(tenant_and_user)
    _, msg = _pending_draft(db, tenant_id)
    llm = _BrokenLLM(RuntimeError("provider 500"))

    class _Retry(Exception):
        pass

    with patch.object(draft_module, "get_llm", return_value=llm), \
         patch.object(draft_module, "SessionLocal", return_value=db), \
         patch.object(rewrite_draft, "retry", side_effect=_Retry()) as retry:
        with pytest.raises(_Retry):
            rewrite_draft.run(message_id=msg.id, tenant_id=tenant_id)
    assert llm.calls == 1 and retry.call_count == 1
    assert retry.call_args.kwargs["exc"].args == ("provider 500",)
    assert rewrite_draft.max_retries == 1                    # so a failing provider is asked at most twice in total


def test_draft_task_treats_the_celery_soft_limit_like_a_timeout(db, tenant_and_user):
    tenant_id = _tenant_id(tenant_and_user)
    _, msg = _pending_draft(db, tenant_id)
    llm = _BrokenLLM(SoftTimeLimitExceeded())
    with patch.object(draft_module, "get_llm", return_value=llm), \
         patch.object(draft_module, "SessionLocal", return_value=db), \
         patch.object(rewrite_draft, "retry", side_effect=AssertionError("the soft limit must not be retried")):
        rewrite_draft.run(message_id=msg.id, tenant_id=tenant_id)
    assert llm.calls == 1


# ── the composer task ──────────────────────────────────────────────────────────────────────────────────────

def test_composer_task_reports_a_hung_provider_as_failed_timeout_after_one_request(quick_timeout, cache):
    llm = _HungLLM()
    job_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())

    started = time.monotonic()
    with patch.object(composer_module, "get_llm", return_value=llm):
        composer_rewrite.run(job_id=job_id, tenant_id=tenant_id, text="Hi, is the villa free?", tone="formal")

    assert time.monotonic() - started < MUST_END_BY
    assert llm.calls == 1
    assert cache == {f"composer_rewrite:{tenant_id}:{job_id}": {"status": "failed", "error": "timeout"}}


def test_composer_task_never_retries_a_provider_error(cache):
    llm = _BrokenLLM(RuntimeError("provider down"))
    job_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    with patch.object(composer_module, "get_llm", return_value=llm), \
         patch.object(composer_rewrite, "retry", side_effect=AssertionError("composer must not retry")):
        composer_rewrite.run(job_id=job_id, tenant_id=tenant_id, text="Hi there")
    assert llm.calls == 1
    assert cache[f"composer_rewrite:{tenant_id}:{job_id}"] == {"status": "failed", "error": "internal_error"}


def test_what_the_person_sees_a_timed_out_composer_job_through_the_status_endpoint(client, db, tenant_and_user, quick_timeout, cache):
    tenant_id = _tenant_id(tenant_and_user)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Priya", phone="+919999011223")
    db.add(guest); db.commit()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    job_id = str(uuid.uuid4())

    with patch.object(composer_module, "get_llm", return_value=_HungLLM()):
        composer_rewrite.run(job_id=job_id, tenant_id=tenant_id, text="hi is it free")

    with patch("app.core.cache.get_cached", side_effect=lambda key: cache.get(key)):
        resp = client.get(f"/api/v1/conversations/{conv.id}/composer/rewrite/{job_id}",
                          headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "failed", "error": "timeout"}   # the page turns "failed" into its error toast


# ── the bounds themselves ──────────────────────────────────────────────────────────────────────────────────

def test_the_worst_case_durations_are_the_documented_ones():
    assert draft_module.REWRITE_TIMEOUT_SECONDS == 30
    # draft: a timeout ends after one request (30 s); a provider error is retried once: 30 + 10 + 30 = 70 s at most
    worst_draft = (rewrite_draft.max_retries + 1) * draft_module.REWRITE_TIMEOUT_SECONDS \
        + rewrite_draft.max_retries * rewrite_draft.default_retry_delay
    assert worst_draft == 70
    # composer: a single request, never retried
    assert draft_module.REWRITE_TIMEOUT_SECONDS == 30


@pytest.mark.parametrize("task", [rewrite_draft, composer_rewrite], ids=["draft", "composer"])
def test_both_tasks_carry_celery_time_limits_as_a_backstop(task):
    soft, hard = task.soft_time_limit, task.time_limit
    assert soft == draft_module.REWRITE_SOFT_TIME_LIMIT and hard == draft_module.REWRITE_HARD_TIME_LIMIT
    assert draft_module.REWRITE_TIMEOUT_SECONDS < soft < hard <= draft_module.REWRITE_TIMEOUT_SECONDS + 60
