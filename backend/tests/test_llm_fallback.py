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


class _SlowThenFast(LLMAdapter):
    """First call hangs past the short bound, later calls answer quickly."""
    provider = "nvidia"

    def __init__(self):
        self.n = 0

    async def complete(self, system_prompt, user_message, model=None, max_tokens=4096, tools=None, **kw):
        self.n += 1
        await asyncio.sleep(5 if self.n == 1 else 0)
        return {"content": "late but fine", "tool_use": None}


def test_a_slow_primary_gets_one_longer_attempt_when_the_fallback_is_down_too():
    """Ratha, Oct 2026: NVIDIA merely slower than the short bound while
    Gemini (no billing credit) failed outright -- the call must not die."""
    primary = _SlowThenFast()
    secondary = _Fake("gemini", exc=RuntimeError("402 prepayment credits are depleted"))
    result = _run(_adapter(primary, secondary, timeout=0.05).complete("sys", "user"))
    assert result["content"] == "late but fine"
    assert primary.n == 2


def test_a_primary_error_that_is_not_a_timeout_is_not_retried_longer():
    primary = _Fake("nvidia", exc=RuntimeError("Error code: 500"))
    secondary = _Fake("gemini", exc=RuntimeError("down"))
    with pytest.raises(RuntimeError, match="500"):
        _run(_adapter(primary, secondary).complete("sys", "user"))
    assert len(primary.calls) == 2   # the two normal attempts, no extra longer one


class _Flaky(_Fake):
    """Fails the first call, then answers: NVIDIA's random hang (live, 25 Oct 2026)."""

    async def complete(self, system_prompt, user_message, model=None, max_tokens=4096, tools=None, **kw):
        self.calls.append({"model": model})
        if len(self.calls) == 1:
            raise RuntimeError("Error code: 504")
        return dict(self._result)


def test_a_second_free_primary_attempt_runs_before_the_paid_fallback():
    primary, secondary = _Flaky("nvidia"), _Fake("gemini")
    adapter = FallbackAdapter(primary, secondary, task="call_scoring", primary_timeout=1.0, primary_attempts=2)
    result = _run(adapter.complete("sys", "user"))
    assert result["content"] == "nvidia" and len(primary.calls) == 2
    assert secondary.calls == []


def test_single_attempt_goes_straight_to_the_fallback():
    primary, secondary = _Flaky("nvidia"), _Fake("gemini")
    adapter = FallbackAdapter(primary, secondary, task="analyst_followup", primary_timeout=1.0, primary_attempts=1)
    assert _run(adapter.complete("sys", "user"))["content"] == "gemini"
    assert len(primary.calls) == 1


def test_fallback_runs_on_the_low_gemini_model(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "test-key")
    adapter = get_llm("lead_summary")
    assert isinstance(adapter, FallbackAdapter)
    assert adapter._secondary._default_model == "gemini-3.1-flash-lite"
    assert adapter._primary_attempts == 2
    assert get_llm("analyst_followup")._primary_attempts == 1


def test_gemini_model_names_pass_through_unmapped():
    from app.adapters.llm.gemini import _map_model
    assert _map_model("gemini-3.1-flash-lite") == "gemini-3.1-flash-lite"
    assert _map_model("gemini-2.5-flash") == "gemini-3.6-flash"   # blocked for new keys: still remapped
    assert _map_model("claude-haiku") == "gemini-3.6-flash"
