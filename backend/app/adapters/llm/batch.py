"""Claude Message Batches (half price, asynchronous) for LLM work nobody waits on. Router-owned: services never see it.

A batched job runs TWICE, with the job's own code unchanged (workers/tasks/llm_batch.py drives it):

  1. collect: `with collecting(tenant_id): job()` -- every get_llm(task).complete() in the job is answered with an empty
     stub (MeteredAdapter -> intercept()), and the calls of tasks switched on in BATCH_TASKS are recorded as batch
     requests. The job must not keep anything from this pass (no commit, no send).
  2. replay: once the batch has ended, `with replaying(results): job()` -- a complete() whose request matches a result
     (same custom_id) gets that result; any other call (the batch failed or expired, one request errored, the job's data
     changed in between) goes to the provider as a normal call. So a batch failure never loses work.

custom_id = a hash of (task, tenant, system prompt, user message, max_tokens, tools): results are matched by custom_id,
never by position (the API returns them in any order). Claude provider only: with LLM_FORCE_PROVIDER other than claude
(or no ANTHROPIC_API_KEY) nothing is collected and the job simply runs with normal calls. Results are metered at batch
price (kind llm_call, meta batch: true, half of anthropic_claude.PRICES) when they are fetched, once per batch.

Never batch work a person waits on (a dialog, a reply, a "Run now" button): only the nightly jobs registered in
workers/tasks/llm_batch.JOBS enter collect mode.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
from dataclasses import dataclass, field

import structlog

from app.core.config import settings

log = structlog.get_logger()

# THE list: which tasks' calls go into a batch while a job is collecting. A task set False here (or missing) runs as a
# normal call in the replay pass. Turning one on also needs a job that runs it (workers/tasks/llm_batch.JOBS).
BATCH_TASKS: dict[str, bool] = {
    "outcome_reason": True,  # nightly Won / Lost sweep (lead_outcome.sweep_all_tenants)
    "agent_performance_narrative": True,  # agent day-end email (reports.daily_agent_report_all_tenants)
    "agent_leads_feedback": True,  # agent day-end email
    # Opt-in, no job wired yet: analyst briefs, the weekly Marketing agency steps, the monthly deck.
    "analyst_brief": False,
    "marketing_audit": False,
    "marketing_research": False,
    "marketing_insights": False,
    "marketing_tagging": False,
    "marketing_deck": False,
}

POLL_SECONDS = 600  # most batches end within an hour
MAX_WAIT_HOURS = 25  # the API expires a batch after 24 h; then every call runs normally
_DEFAULT_MAX_TOKENS = 4096  # FallbackAdapter's default, so collect and replay hash the same request


def claude_on() -> bool:
    return settings.LLM_FORCE_PROVIDER.strip().lower() == "claude" and bool(settings.ANTHROPIC_API_KEY)


def enabled(task: str) -> bool:
    return bool(BATCH_TASKS.get(task)) and claude_on()


@dataclass
class Collector:
    tenant_id: str
    requests: dict = field(default_factory=dict)  # custom_id -> {"params": ..., "meta": ...}


@dataclass
class Replay:
    results: dict  # custom_id -> adapter result dict


_mode: contextvars.ContextVar[Collector | Replay | None] = contextvars.ContextVar("llm_batch_mode", default=None)


@contextlib.contextmanager
def collecting(tenant_id: str):
    col = Collector(tenant_id=str(tenant_id))
    token = _mode.set(col)
    try:
        yield col
    finally:
        _mode.reset(token)


@contextlib.contextmanager
def replaying(results: dict):
    token = _mode.set(Replay(results=dict(results or {})))
    try:
        yield
    finally:
        _mode.reset(token)


def custom_id(task: str, tenant_id, system: str, user: str, max_tokens: int, tools) -> str:
    blob = json.dumps([task, str(tenant_id or ""), system, user, max_tokens, tools], sort_keys=True, default=str)
    return "r" + hashlib.sha256(blob.encode()).hexdigest()[:48]  # API limit: 64 chars of [A-Za-z0-9_-]


def _call_args(args: tuple, kwargs: dict) -> tuple:
    """(system, user, max_tokens, tools) from LLMAdapter.complete's arguments, positional or keyword."""
    names = ("system_prompt", "user_message", "model", "max_tokens", "tools")
    given = {**dict(zip(names, args, strict=False)), **kwargs}
    return (
        given.get("system_prompt") or "",
        given.get("user_message") or "",
        int(given.get("max_tokens") or _DEFAULT_MAX_TOKENS),
        given.get("tools"),
    )


def intercept(task: str, tenant_id, args: tuple, kwargs: dict) -> dict | None:
    """Called by MeteredAdapter.complete. None = call the provider as usual."""
    mode = _mode.get()
    if mode is None:
        return None
    from app.adapters.llm.scope import current

    scope = current()
    tid = tenant_id or (scope.tenant_id if scope else None)
    system, user, max_tokens, tools = _call_args(args, kwargs)
    cid = custom_id(task, tid, system, user, max_tokens, tools)
    if isinstance(mode, Replay):
        hit = mode.results.get(cid)
        return dict(hit) if hit is not None else None
    if enabled(task) and str(tid or "") == mode.tenant_id:  # one tenant per batch
        from app.adapters.llm import claude_route
        from app.adapters.llm.anthropic_claude import build_params

        model, effort, _ = claude_route(task)
        mode.requests[cid] = {
            "params": build_params(system, user, model, max_tokens, tools, effort),
            "meta": {
                "task": task,
                "model": model,
                "tools": bool(tools),
                "module": scope.module if scope else None,
                "ref_type": scope.ref_type if scope else None,
                "ref_id": scope.ref_id if scope else None,
                "prompt_version": scope.prompt_version if scope else None,
            },
        }
    # The collect pass is thrown away: callers see an empty answer and degrade as they would on a bad reply.
    return {"content": "", "tool_use": None, "model": None, "batch_deferred": True}


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=2, timeout=120)


def submit(col: Collector) -> str | None:
    """Create the batch. None on any failure (the caller then runs the job with normal calls)."""
    try:
        batch = _client().messages.batches.create(
            requests=[{"custom_id": cid, "params": r["params"]} for cid, r in col.requests.items()]
        )
        log.info("llm_batch_submitted", tenant_id=col.tenant_id, batch_id=batch.id, requests=len(col.requests))
        return batch.id
    except Exception as exc:  # noqa: BLE001 -- the job falls back to normal calls
        log.warning(
            "llm_batch_submit_failed",
            tenant_id=col.tenant_id,
            requests=len(col.requests),
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
        return None


def status(batch_id: str) -> str:
    """'ended' | 'processing' (also when the status could not be read: the next poll tries again)."""
    try:
        return "ended" if _client().messages.batches.retrieve(batch_id).processing_status == "ended" else "processing"
    except Exception as exc:  # noqa: BLE001
        log.warning("llm_batch_status_failed", batch_id=batch_id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return "processing"


def cancel(batch_id: str) -> None:
    try:
        _client().messages.batches.cancel(batch_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("llm_batch_cancel_failed", batch_id=batch_id, error=str(exc)[:200])


def results(batch_id: str, tenant_id: str, metas: dict) -> dict:
    """{custom_id: adapter result} of the requests that succeeded with a usable answer. Every billed answer (a reply
    without the tool call too) is metered here at batch price, once per batch (the caller claims the batch first)."""
    from app.adapters.llm.anthropic_claude import ClaudeNoToolCall, cost_usd, parse_response, usage_of
    from app.adapters.llm.metered import record

    out, counts = {}, {"succeeded": 0, "unusable": 0, "errored": 0, "expired": 0, "canceled": 0, "unknown": 0}
    try:
        items = list(_client().messages.batches.results(batch_id))
    except Exception as exc:  # noqa: BLE001 -- every call then runs normally
        log.warning("llm_batch_results_failed", batch_id=batch_id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return {}
    for item in items:
        meta = metas.get(item.custom_id)
        kind = getattr(item.result, "type", None)
        if meta is None:
            counts["unknown"] += 1
            continue
        if kind != "succeeded":
            counts[kind if kind in counts else "unknown"] += 1
            continue
        msg = item.result.message
        model = getattr(msg, "model", None) or meta["model"]
        usage = usage_of(msg)
        record(
            "llm_call",
            task=meta["task"],
            provider="claude",
            model=model,
            input_units=usage["input_tokens"],
            output_units=usage["output_tokens"],
            units=sum(usage.values()),
            cost_usd=cost_usd(model, usage, batch=True),
            tenant_id=tenant_id,
            module=meta.get("module") or "llm",
            ref_type=meta.get("ref_type"),
            ref_id=meta.get("ref_id"),
            prompt_version=meta.get("prompt_version"),
            batch=True,
            batch_id=batch_id,
            fallback_used=False,
            cache_read_tokens=usage["cache_read_input_tokens"],
            cache_write_tokens=usage["cache_creation_input_tokens"],
        )
        try:
            out[item.custom_id] = parse_response(msg, model, meta["tools"])
            counts["succeeded"] += 1
        except ClaudeNoToolCall:
            counts["unusable"] += 1  # billed, metered above; the replay pass calls the provider normally
    log.info("llm_batch_results", batch_id=batch_id, tenant_id=tenant_id, **counts)
    return out
