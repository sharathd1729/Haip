"""Metering you can trust (AI cost audit W17): the Claude price table, every provider request counted (fallback + retries),
embeddings and vision metered in the same usage_events shape. No network: every provider is a fake."""

import asyncio
from types import SimpleNamespace

import pytest

from app.adapters.llm import metered
from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.fallback import FallbackAdapter
from app.adapters.llm.metered import MeteredAdapter, attempt
from app.adapters.llm.scope import llm_scope


@pytest.fixture
def captured(monkeypatch):
    rows = []
    monkeypatch.setattr(metered, "write_rows", lambda batch: rows.extend(batch))
    return rows


def test_claude_price_table_is_pinned():
    from app.adapters.llm import anthropic_claude as c

    assert c.PRICES == {"claude-sonnet-5-5": (2.00, 10.00, 0.20), "claude-haiku-5-5": (0.10, 0.50, 0.01)}
    assert c.CACHE_WRITE_MULTIPLIER == 1.25 and c.BATCH_DISCOUNT == 0.5
    m = 1_000_000
    assert c.cost_usd("claude-sonnet-5-5", {"cache_read_input_tokens": m}) == 0.20
    assert c.cost_usd("claude-sonnet-5-5", {"cache_creation_input_tokens": m}) == 2.50
    assert c.cost_usd("claude-haiku-5-5", {"input_tokens": m, "output_tokens": m}) == 0.60
    assert c.cost_usd("claude-sonnet-5-5", {"input_tokens": m, "output_tokens": m}, batch=True) == 6.0


class _Recording(LLMAdapter):
    """Sends `requests` provider requests (each an attempt with its tokens), then answers or raises."""

    def __init__(self, provider, model, requests, result=None, exc=None):
        self.provider, self._default_model = provider, model
        self.requests, self.result, self.exc = requests, result, exc

    async def complete(self, *args, **kwargs):
        for model, inp, out in self.requests:
            rec = attempt(self.provider, model)
            rec.update(input_tokens=inp, output_tokens=out)
        if self.exc:
            raise self.exc
        return self.result


def test_fallback_attempts_and_their_tokens_are_summed(captured):
    # Claude answered without the tool (billed), then Gemini's first answer was a malformed call and its retry worked.
    claude = _Recording("claude", "claude-sonnet-5-5", [("claude-sonnet-5-5", 1000, 500)], exc=RuntimeError("no tool"))
    gemini = _Recording(
        "gemini",
        "gemini-3.1-flash-lite",
        [("gemini-3.1-flash-lite", 2000, 100), ("gemini-3.1-flash-lite", 2000, 300)],
        result={"content": "ok", "input_tokens": 2000, "output_tokens": 300, "model": "gemini-3.1-flash-lite"},
    )
    fb = FallbackAdapter(primary=claude, secondary=gemini, task="outcome_reason", primary_timeout=5, primary_attempts=1)
    asyncio.run(MeteredAdapter(fb, "outcome_reason", tenant_id="t1").complete("s", "u"))
    (row,) = captured
    m = row["meta"]
    assert m["attempts"] == 3 and m["fallback_used"] and row["provider"] == "gemini"
    assert row["input_units"] == 5000 and row["output_units"] == 900 and row["units"] == m["attempt_tokens"] == 5900
    claude_cost = (1000 * 2.0 + 500 * 10.0) / 1e6
    gemini_cost = (4000 * 0.25 + 400 * 1.50) / 1e6
    assert m["cost_usd"] == round(claude_cost + gemini_cost, 6)


def test_failed_call_still_counts_billed_attempts(captured):
    bad = _Recording("claude", "claude-sonnet-5-5", [("claude-sonnet-5-5", 100, 50)], exc=ValueError("refused"))
    with pytest.raises(ValueError):
        asyncio.run(MeteredAdapter(bad, "x", tenant_id="t1").complete("s", "u"))
    assert captured[0]["meta"]["ok"] is False and captured[0]["meta"]["cost_usd"] == round(700 / 1e6, 6)


def test_attempt_without_reply_costs_nothing_and_unknown_price_is_null(captured):
    timed_out = _Recording("claude", "claude-sonnet-5-5", [("claude-sonnet-5-5", 0, 0)], exc=TimeoutError())
    with pytest.raises(TimeoutError):
        asyncio.run(MeteredAdapter(timed_out, "x", tenant_id="t1").complete("s", "u"))
    assert captured[-1]["meta"]["attempts"] == 1 and captured[-1]["meta"]["cost_usd"] == 0.0
    unknown = _Recording(
        "gemini",
        "gemini-flash-latest",
        [("gemini-flash-latest", 10, 10)],
        result={"content": "", "model": "gemini-flash-latest"},
    )
    asyncio.run(MeteredAdapter(unknown, "x", tenant_id="t1").complete("s", "u"))
    assert captured[-1]["meta"]["cost_usd"] is None  # never guessed


def test_claude_adapter_records_a_billed_reply_without_the_tool_call(captured, monkeypatch):
    from app.adapters.llm import anthropic_claude as c

    reply = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="prose")],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0
        ),
    )
    adapter = c.ClaudeAdapter()

    async def create(**_):
        return reply

    monkeypatch.setattr(adapter._client.messages, "create", create)
    with pytest.raises(c.ClaudeNoToolCall):
        asyncio.run(
            MeteredAdapter(adapter, "x", tenant_id="t1").complete(
                "s",
                "u",
                tools=[{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}],
            )
        )
    assert captured[0]["meta"]["attempts"] == 1 and captured[0]["meta"]["cost_usd"] == round(4000 / 1e6, 6)


def test_record_follows_the_scope_and_logs_without_a_tenant(captured, monkeypatch):
    with llm_scope(tenant_id="t7", module="knowledge", ref_type="knowledge_entry", ref_id="e1"):
        metered.record(
            "embedding_call", task="embed_passage", provider="nvidia", model="m", input_units=12, cost_usd=0.0
        )
    (row,) = captured
    assert row["tenant_id"] == "t7" and row["kind"] == "embedding_call" and row["ref_id"] == "e1" and row["units"] == 12
    lines = []
    monkeypatch.setattr(metered.log, "info", lambda event, **kw: lines.append(event))
    metered.record("vision_call", task="vision_photo", provider="gemini", model="m")
    assert len(captured) == 1 and lines == ["vision_call"]


def test_embeddings_are_metered(captured, monkeypatch):
    import openai

    from app.adapters.llm import embeddings
    from app.core.config import settings

    class _Emb:
        async def create(self, model, input, extra_body):
            return SimpleNamespace(
                data=[SimpleNamespace(index=i, embedding=[0.0] * embeddings.EMBED_DIM) for i in range(len(input))],
                usage=SimpleNamespace(prompt_tokens=7 * len(input)),
            )

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "k")
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_: SimpleNamespace(embeddings=_Emb()))
    with llm_scope(tenant_id="t3", module="knowledge"):
        assert len(embeddings.embed_texts_sync(["a", "b"], "passage")) == 2
    (row,) = captured
    assert row["kind"] == "embedding_call" and row["tenant_id"] == "t3" and row["input_units"] == 14
    assert row["meta"]["task"] == "embed_passage" and row["meta"]["cost_usd"] == 0.0


def test_vision_is_metered_even_when_the_answer_is_unreadable(captured, monkeypatch):
    from app.adapters import vision
    from app.adapters.vision import gemini as vg
    from app.core.config import settings

    body = {
        "candidates": [{"content": {"parts": [{"text": "not json"}]}}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 100, "thoughtsTokenCount": 50},
    }
    client = SimpleNamespace(post=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: body, text=""))
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k")
    with llm_scope(tenant_id="t4", module="ops"), pytest.raises(vision.VisionError):
        vg.describe(vision.get_model(None), b"jpeg", "look", client=client)
    (row,) = captured
    assert row["kind"] == "vision_call" and row["tenant_id"] == "t4" and row["module"] == "ops"
    assert row["input_units"] == 1000 and row["output_units"] == 150 and row["meta"]["cost_usd"] is not None


def test_vision_embedding_and_phrasing_tasks_run_in_a_tenant_scope(captured, monkeypatch):
    """The Celery tasks that read photos / embed KB entries (and write their phrasings) carry the tenant to the meter."""
    from app.workers.tasks import embed_knowledge, marketing_research_tasks, marketing_studio, ops_intake

    for task in (
        embed_knowledge.embed_entry,
        ops_intake.process_staff_photo,
        marketing_studio.tag_photo,
        marketing_research_tasks.read_video,
    ):
        assert hasattr(task.run, "__wrapped__"), task.name  # functools.wraps of scoped_task
    seen = []
    monkeypatch.setattr(embed_knowledge, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("stop")))
    from app.adapters.llm import scope as scope_mod

    real = scope_mod.llm_scope

    def spy(**kw):
        seen.append(kw)
        return real(**kw)

    monkeypatch.setattr(scope_mod, "llm_scope", spy)
    with pytest.raises(RuntimeError):
        embed_knowledge.embed_pending.run("tenant-42")
    assert seen and seen[0]["tenant_id"] == "tenant-42" and seen[0]["module"] == "knowledge"
