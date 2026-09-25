"""NVIDIA -> Gemini fallback for internal-analysis LLM tasks."""

import asyncio

import pytest

from app.adapters.llm import get_llm
from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.fallback import FallbackAdapter
from app.core.config import settings


class _Fake(LLMAdapter):
    def __init__(self, provider, result=None, exc=None, delay=0.0):
        self.provider = provider
        self._result = result or {"content": provider, "tool_use": None}
        self._exc = exc
        self._delay = delay
        self.calls = []

    async def complete(self, system_prompt, user_message, model=None, max_tokens=4096, tools=None, **kw):
        self.calls.append({"model": model, "max_tokens": max_tokens, "tools": tools, **kw})
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc:
            raise self._exc
        return dict(self._result)


def _run(coro):
    return asyncio.run(coro)


def _adapter(primary, secondary, timeout=1.0):
    return FallbackAdapter(primary, secondary, task="call_scoring", primary_timeout=timeout)


def test_primary_success_never_touches_the_secondary():
    primary, secondary = _Fake("nvidia"), _Fake("gemini")
    result = _run(_adapter(primary, secondary).complete("sys", "user"))
    assert result["content"] == "nvidia"
    assert "fallback_used" not in result
    assert secondary.calls == []


def test_primary_error_retries_on_the_secondary():
    primary = _Fake("nvidia", exc=RuntimeError("Error code: 504"))
    secondary = _Fake("gemini")
    result = _run(_adapter(primary, secondary).complete("sys", "user", tools=[{"name": "t"}]))
    assert result["content"] == "gemini"
    assert result["fallback_used"] is True
    assert secondary.calls[0]["tools"] == [{"name": "t"}]


def test_primary_hang_times_out_and_falls_back():
    primary = _Fake("nvidia", delay=5)
    secondary = _Fake("gemini")
    result = _run(_adapter(primary, secondary, timeout=0.05).complete("sys", "user"))
    assert result["fallback_used"] is True


def test_the_primary_models_name_and_kwargs_are_not_sent_to_the_secondary():
    primary = _Fake("nvidia", exc=RuntimeError("504"))
    secondary = _Fake("gemini")
    _run(_adapter(primary, secondary).complete("sys", "user", model="openai/gpt-oss-20b", thinking=True))
    assert primary.calls[0]["model"] == "openai/gpt-oss-20b"
    assert secondary.calls[0]["model"] is None
    assert "thinking" not in secondary.calls[0]


def test_when_both_fail_the_primarys_error_surfaces():
    primary = _Fake("nvidia", exc=RuntimeError("primary boom"))
    secondary = _Fake("gemini", exc=ValueError("secondary boom"))
    with pytest.raises(RuntimeError, match="primary boom"):
        _run(_adapter(primary, secondary).complete("sys", "user"))


def test_provider_attribute_stays_the_primarys():
    assert _adapter(_Fake("nvidia"), _Fake("gemini")).provider == "nvidia"


def test_get_llm_wraps_analysis_tasks_when_a_gemini_key_is_set(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    for task in ("call_scoring", "call_analysis", "lead_summary", "quick_classify", "deep_reason"):
        assert isinstance(get_llm(task), FallbackAdapter), task


def test_get_llm_does_not_wrap_without_a_gemini_key(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    assert not isinstance(get_llm("call_scoring"), FallbackAdapter)


def test_get_llm_leaves_other_tasks_alone(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    assert not isinstance(get_llm("concierge_draft"), FallbackAdapter)   # already Gemini
    assert not isinstance(get_llm("ask_haip_freeform_sql"), FallbackAdapter)
