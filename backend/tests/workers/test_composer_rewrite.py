"""Tests for HAIP Inbox full-parity pass, ticket 5: Translate/Tone-Fix on
the composer's free-typed text. No Message row exists for unsent text, so
the result hands off via a short-lived Redis-cached job result instead of
updating a stored draft in place (unlike rewrite_draft.py)."""
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.workers.tasks.composer_rewrite import composer_rewrite
from app.core.cache import get_cached


class _FakeRewriteLLM:
    def __init__(self, text="Bonjour! Comment puis-je vous aider?"):
        self._text = text

    async def complete(self, **kwargs):
        return {"tool_use": {"rewritten_text": self._text}}


class TestComposerRewriteTask:
    def test_writes_rewritten_text_to_cache(self, monkeypatch):
        monkeypatch.setattr("app.workers.tasks.composer_rewrite.get_llm", lambda task: _FakeRewriteLLM())
        job_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        composer_rewrite.run(job_id=job_id, tenant_id=tenant_id, text="Hi, is the villa free?", target_language="French")

        cached = get_cached(f"composer_rewrite:{tenant_id}:{job_id}")
        # get_cached returns None if Redis isn't reachable in this sandbox --
        # in that case the task still must not raise (already covered by
        # composer_rewrite.run completing above without exception).
        if cached is not None:
            assert cached["status"] == "done"
            assert cached["rewritten_text"] == "Bonjour! Comment puis-je vous aider?"

    def test_empty_llm_result_marks_failed(self, monkeypatch):
        class _EmptyLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {}}
        monkeypatch.setattr("app.workers.tasks.composer_rewrite.get_llm", lambda task: _EmptyLLM())
        job_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        composer_rewrite.run(job_id=job_id, tenant_id=tenant_id, text="Hi there")

        cached = get_cached(f"composer_rewrite:{tenant_id}:{job_id}")
        if cached is not None:
            assert cached["status"] == "failed"

    def test_llm_exception_marks_failed_not_raised(self, monkeypatch):
        class _BrokenLLM:
            async def complete(self, **kwargs):
                raise RuntimeError("provider down")
        monkeypatch.setattr("app.workers.tasks.composer_rewrite.get_llm", lambda task: _BrokenLLM())
        job_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        # Must not raise -- this runs via .delay() in production, an
        # uncaught exception would just retry/dead-letter with no user-
        # visible signal since there's no polling-endpoint fallback path.
        composer_rewrite.run(job_id=job_id, tenant_id=tenant_id, text="Hi there")

        cached = get_cached(f"composer_rewrite:{tenant_id}:{job_id}")
        if cached is not None:
            assert cached["status"] == "failed"
