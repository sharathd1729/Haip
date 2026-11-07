"""LLM metering (adapters/llm/metered.py + scope.py): one usage_events row (kind="llm_call") per get_llm().complete() call,
numbers and labels only, never in the way of the call it measures. No network: every provider is a fake."""

import asyncio
from datetime import date

import pytest

from app.adapters.llm import metered
from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.fallback import FallbackAdapter
from app.adapters.llm.metered import MeteredAdapter
from app.adapters.llm.metered import write_rows as REAL_WRITE_ROWS  # conftest stubs it per test
from app.adapters.llm.scope import llm_scope, scoped_task

SECRET_PROMPT = "guest Priya +919800000000 wants Coorg"
SECRET_REPLY = "Hi Priya, Coorg is lovely in May"


class _Fake(LLMAdapter):
    def __init__(self, provider="gemini", model="gemini-3.6-flash", result=None, exc=None, delay=0.0):
        self.provider, self._default_model = provider, model
        self.result, self.exc, self.delay, self.calls = result, exc, delay, []

    async def complete(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result


def _gemini_result():
    return {
        "content": SECRET_REPLY,
        "tool_use": {"reply": SECRET_REPLY},
        "input_tokens": 1000,
        "output_tokens": 200,
        "model": "gemini-3.6-flash",
    }


@pytest.fixture
def captured(monkeypatch):
    rows = []
    monkeypatch.setattr(metered, "write_rows", lambda batch: rows.extend(batch))
    return rows


def test_result_and_arguments_pass_through_unchanged(captured):
    result = _gemini_result()
    inner = _Fake(result=result)
    adapter = MeteredAdapter(inner, "concierge_draft")
    out = asyncio.run(adapter.complete(system_prompt="s", user_message="u", tools=None, thinking=True))
    assert out is result and out == _gemini_result()  # same object, nothing added
    assert inner.calls == [
        ((), {"system_prompt": "s", "user_message": "u", "tools": None, "thinking": True})
    ]  # no defaults injected


def test_exception_is_reraised_unchanged(captured):
    boom = RuntimeError("provider down")
    adapter = MeteredAdapter(_Fake(exc=boom), "lead_summary")
    with llm_scope(tenant_id="t1"):
        with pytest.raises(RuntimeError) as info:
            asyncio.run(adapter.complete("s", "u"))
    assert info.value is boom
    assert captured[0]["meta"]["ok"] is False and captured[0]["meta"]["error_class"] == "RuntimeError"
    assert captured[0]["meta"]["cost_usd"] is None  # failed paid call: unknown, never guessed


def test_provider_default_model_and_inner_are_exposed():
    inner = _Fake(provider="nvidia", model="openai/gpt-oss-20b")
    adapter = MeteredAdapter(inner, "call_scoring")
    assert adapter.provider == "nvidia" and adapter._default_model == "openai/gpt-oss-20b" and adapter.inner is inner


def test_get_llm_always_returns_a_metered_adapter():
    from app.adapters.llm import get_llm, get_llm_adapter

    for task in ("concierge_draft", "call_analysis", "no_such_task"):
        assert isinstance(get_llm(task), MeteredAdapter)
    assert isinstance(get_llm_adapter("nvidia"), MeteredAdapter)


def test_one_row_per_call_with_the_expected_fields_and_no_text(captured):
    adapter = MeteredAdapter(_Fake(result=_gemini_result()), "concierge_draft")
    with llm_scope(
        tenant_id="t1", module="concierge", ref_type="message", ref_id="m1", prompt_version="concierge-reply-v20"
    ):
        asyncio.run(adapter.complete(system_prompt=SECRET_PROMPT, user_message=SECRET_PROMPT))
        asyncio.run(adapter.complete(system_prompt=SECRET_PROMPT, user_message=SECRET_PROMPT))
        assert captured == []  # nothing written while the scope is open
    assert len(captured) == 2
    row = captured[0]
    assert {
        k: row[k]
        for k in (
            "tenant_id",
            "module",
            "kind",
            "provider",
            "model",
            "units",
            "input_units",
            "output_units",
            "ref_type",
            "ref_id",
        )
    } == {
        "tenant_id": "t1",
        "module": "concierge",
        "kind": "llm_call",
        "provider": "gemini",
        "model": "gemini-3.6-flash",
        "units": 1200,
        "input_units": 1000,
        "output_units": 200,
        "ref_type": "message",
        "ref_id": "m1",
    }
    meta = row["meta"]
    assert set(meta) == {"task", "latency_ms", "ok", "error_class", "fallback_used", "cost_usd", "prompt_version"}
    assert meta["task"] == "concierge_draft" and meta["ok"] is True and meta["error_class"] is None
    assert meta["fallback_used"] is False and meta["prompt_version"] == "concierge-reply-v20"
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0
    text = repr(captured)
    assert "Priya" not in text and "Coorg" not in text and "9800000000" not in text


def test_nested_scope_inherits_and_shares_one_write(captured):
    adapter = MeteredAdapter(_Fake(result=_gemini_result()), "quick_classify")
    with llm_scope(tenant_id="t1", module="concierge", prompt_version="concierge-reply-v20"):
        with llm_scope(prompt_version="concierge-intent-v3"):
            asyncio.run(adapter.complete("s", "u"))
        assert captured == []  # the inner scope does not write
        asyncio.run(adapter.complete("s", "u"))
    assert [r["meta"]["prompt_version"] for r in captured] == ["concierge-intent-v3", "concierge-reply-v20"]
    assert {r["tenant_id"] for r in captured} == {"t1"} and {r["module"] for r in captured} == {"concierge"}


def test_fallback_records_the_provider_that_answered(captured):
    primary = _Fake(provider="nvidia", model="openai/gpt-oss-20b", exc=RuntimeError("504"))
    secondary = _Fake(
        provider="gemini",
        model="gemini-3.1-flash-lite",
        result={
            "content": "ok",
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "model": "gemini-3.1-flash-lite",
        },
    )
    adapter = MeteredAdapter(
        FallbackAdapter(primary, secondary, task="lead_summary", primary_timeout=5, primary_attempts=1), "lead_summary"
    )
    with llm_scope(tenant_id="t1"):
        asyncio.run(adapter.complete("s", "u", thinking=True))
    assert len(captured) == 1  # a fallback is one call, one row
    row = captured[0]
    assert row["provider"] == "gemini" and row["model"] == "gemini-3.1-flash-lite"
    assert row["meta"]["fallback_used"] is True and row["meta"]["cost_usd"] == 1.75  # $0.25 in + $1.50 out per M
    assert "thinking" not in secondary.calls[0][1]  # FallbackAdapter still drops it for the secondary


def test_nested_claude_switch_fallback_names_the_deepest_provider(captured):
    gem = _Fake(
        provider="gemini",
        model="gemini-3.1-flash-lite",
        result={"content": "ok", "input_tokens": 10, "output_tokens": 10, "model": "gemini-3.1-flash-lite"},
    )
    nim = _Fake(provider="nvidia", model="openai/gpt-oss-20b", exc=RuntimeError("504"))
    routed = FallbackAdapter(nim, gem, task="call_analysis", primary_timeout=5, primary_attempts=1)
    claude = _Fake(provider="claude", model="claude-sonnet-5-5", exc=RuntimeError("overloaded"))
    adapter = MeteredAdapter(
        FallbackAdapter(claude, routed, task="call_analysis", primary_timeout=5, primary_attempts=1), "call_analysis"
    )
    assert adapter.provider == "claude"
    with llm_scope(tenant_id="t1"):
        asyncio.run(adapter.complete("s", "u"))
    assert captured[0]["provider"] == "gemini"


def test_cost_per_provider():
    from app.adapters.llm.gemini import cost_usd as gemini_cost

    assert metered.cost_usd("nvidia", "openai/gpt-oss-20b", {"input_tokens": 9_999}, ok=True) == 0.0
    claude = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 0}
    assert metered.cost_usd("claude", "claude-sonnet-5-5", claude, ok=True) == 12.0
    assert metered.cost_usd("claude", "claude-unknown", claude, ok=True) is None
    assert gemini_cost("gemini-3.6-flash", 1_000_000, 1_000_000, today=date(2026, 12, 31)) == 4.5
    assert gemini_cost("gemini-3.6-flash", 1_000_000, 1_000_000, today=date(2027, 1, 1)) == 9.0  # price doubles
    assert gemini_cost("gemini-9-ultra", 1_000_000, 1_000_000) is None  # unknown: null, never a guess


def test_no_tenant_logs_one_line_and_writes_nothing(captured, monkeypatch):
    lines = []
    monkeypatch.setattr(metered.log, "info", lambda event, **kw: lines.append((event, kw)))
    asyncio.run(MeteredAdapter(_Fake(result=_gemini_result()), "assessment_narrative").complete("s", "u"))
    assert captured == [] and len(lines) == 1 and lines[0][0] == "llm_call"
    assert lines[0][1]["meta"]["task"] == "assessment_narrative" and "tenant_id" not in lines[0][1]


def test_tenant_from_get_llm_without_a_scope_writes_at_once(captured):
    asyncio.run(MeteredAdapter(_Fake(result=_gemini_result()), "marketing_plan", tenant_id="t9").complete("s", "u"))
    assert len(captured) == 1 and captured[0]["tenant_id"] == "t9" and captured[0]["module"] == "llm"


def test_metering_failures_never_reach_the_caller(monkeypatch):
    def broken(*a, **k):
        raise ValueError("bad metering")

    monkeypatch.setattr(metered, "build_row", broken)
    result = _gemini_result()
    with llm_scope(tenant_id="t1"):
        assert asyncio.run(MeteredAdapter(_Fake(result=result), "x").complete("s", "u")) is result

    monkeypatch.setattr(metered, "_new_session", broken)  # the database is down
    REAL_WRITE_ROWS([{"tenant_id": "t1", "module": "m", "kind": "llm_call", "units": 1, "meta": {}}])  # does not raise


def test_a_timed_out_call_is_counted_and_the_timeout_still_raised(captured):
    adapter = MeteredAdapter(_Fake(result=_gemini_result(), delay=5), "concierge_draft")

    async def run():
        return await asyncio.wait_for(adapter.complete("s", "u"), timeout=0.05)

    with llm_scope(tenant_id="t1"):
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(run())
    assert captured[0]["meta"]["ok"] is False and captured[0]["meta"]["error_class"] == "CancelledError"


def test_scoped_task_takes_tenant_and_ref_from_arguments_and_writes_after_the_task(monkeypatch):
    order = []
    monkeypatch.setattr(metered, "write_rows", lambda rows: order.append(("write", [r["ref_id"] for r in rows])))
    adapter = MeteredAdapter(_Fake(result=_gemini_result()), "concierge_draft")

    @scoped_task("concierge", ref_type="message", ref_arg="message_id", prompt_key="concierge_reply")
    def task(self, message_id, conversation_id, tenant_id):
        loop = asyncio.new_event_loop()  # how the Celery tasks run coroutines
        try:
            loop.run_until_complete(adapter.complete("s", "u"))
        finally:
            loop.close()
        order.append(("db.close", None))

    task(object(), "m1", "c1", tenant_id="t1")
    assert order == [("db.close", None), ("write", ["m1"])]


def test_rows_land_in_usage_events_for_their_tenant_only(db, tenant_and_user, monkeypatch):
    from app.models.tenant import Tenant
    from app.models.usage_event import UsageEvent

    class _SameSession:  # the writer's own session, inside the test transaction
        def __getattr__(self, name):
            return getattr(db, name)

        def commit(self):
            db.flush()

        def close(self):
            pass

    other = Tenant(id="other-tenant-metering", name="Other", slug="other-metering", plan="growth")
    db.add(other)
    db.flush()
    monkeypatch.setattr(metered, "write_rows", REAL_WRITE_ROWS)
    monkeypatch.setattr(metered, "_new_session", lambda: _SameSession())
    tenant_id = tenant_and_user["tenant"].id
    with llm_scope(
        tenant_id=tenant_id, module="leads", ref_type="inquiry", ref_id="i1", prompt_version="leads360-summary-v10"
    ):
        asyncio.run(
            MeteredAdapter(_Fake(result=_gemini_result()), "lead_summary").complete(SECRET_PROMPT, SECRET_PROMPT)
        )
    rows = db.query(UsageEvent).filter_by(tenant_id=tenant_id, kind="llm_call").all()
    assert len(rows) == 1 and rows[0].module == "leads" and rows[0].meta["task"] == "lead_summary"
    from app.adapters.llm.gemini import cost_usd as gemini_cost

    assert rows[0].meta["cost_usd"] == gemini_cost("gemini-3.6-flash", 1000, 200) > 0  # dated price table
    assert db.query(UsageEvent).filter_by(tenant_id=other.id).count() == 0
