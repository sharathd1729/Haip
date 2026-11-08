"""MeteredAdapter: one `usage_events` row (kind="llm_call") per get_llm(task).complete() call. Numbers and labels only, never
the prompt or the output text.

It wraps whatever get_llm() built (the routed adapter, the NVIDIA->Gemini FallbackAdapter or the LLM_FORCE_PROVIDER=claude
FallbackAdapter), so a fallback is ONE call and ONE row, with the provider that actually answered. Arguments go to the inner
adapter exactly as given (provider-specific kwargs such as thinking= included), the result comes back unchanged and an
exception is re-raised unchanged. Metering never breaks the work it measures: every error in here is logged and swallowed.

Every provider REQUEST is an attempt (`attempt()`, called by the Claude / Gemini / NVIDIA adapters right before each HTTP
request): a FallbackAdapter can send up to four, Gemini's MALFORMED_FUNCTION_CALL path two more. The row keeps the
answering provider and model, but its tokens and cost are the SUM over every attempt that got a reply (meta `attempts`,
`attempt_tokens`), so spend on retries is not lost; a Claude reply without the tool call is billed, so it is counted. An
adapter that reports no attempts (test doubles, the unused OpenAI adapter) is metered from its result, as before.

Where the row goes (adapters/llm/scope.py): inside a scope, into the scope's rows, written when the outermost scope exits;
no scope but get_llm() was given a tenant_id: written now in its own short session; no tenant at all: one structured
log line instead (usage_events.tenant_id is NOT NULL). Cost reports read kind="llm_call", "embedding_call" and
"vision_call"; the Studio's older `llm_tokens` / `vision` / `video_read` rows (usage_service) stay as they are, so nothing
is counted twice.

`record()` writes other model use in the same shape: kind `embedding_call` (adapters/llm/embeddings.py), `vision_call`
(adapters/vision/gemini.py) and Message Batches results (adapters/llm/batch.py: `llm_call`, meta `batch: true`, half price).
"""

from __future__ import annotations

import contextvars
import time
from itertools import groupby

import structlog

from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.scope import current

log = structlog.get_logger()

# The attempt records of the call being metered; the list is shared with every asyncio task the call spawns (wait_for).
_attempts: contextvars.ContextVar[list | None] = contextvars.ContextVar("llm_attempts", default=None)

_TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def attempt(provider: str, model: str | None) -> dict:
    """One provider request about to be sent. The adapter fills input_tokens / output_tokens (and Claude's cache tokens)
    into the returned dict when the reply arrives; a request that fails keeps zeros (no reply, not billed)."""
    rec = {"provider": provider, "model": model, **dict.fromkeys(_TOKEN_KEYS, 0)}
    atts = _attempts.get()
    if atts is not None:
        atts.append(rec)
    return rec


class MeteredAdapter(LLMAdapter):
    def __init__(self, inner: LLMAdapter, task: str, tenant_id: str | None = None):
        self.inner = inner
        self._task = task
        self._tenant_id = tenant_id
        self.provider = getattr(inner, "provider", None)

    @property
    def _default_model(self):
        return getattr(self.inner, "_default_model", None)

    async def complete(self, *args, **kwargs) -> dict:
        from app.adapters.llm import batch

        served = batch.intercept(self._task, self._tenant_id, args, kwargs)   # Message Batches collect / replay
        if served is not None:
            return served
        atts: list = []
        token = _attempts.set(atts)
        start = time.monotonic()
        try:
            result = await self.inner.complete(*args, **kwargs)
        except BaseException as exc:  # a timeout cancels the call (CancelledError): it is still a failed call to count
            self._meter(None, start, exc, atts)
            raise
        finally:
            _attempts.reset(token)
        self._meter(result, start, None, atts)
        return result

    def _meter(self, result, start: float, exc: BaseException | None, atts: list | None = None) -> None:
        try:
            route(build_row(self, result if isinstance(result, dict) else {}, int((time.monotonic() - start) * 1000),
                            exc, current(), atts))
        except Exception as meter_exc:  # noqa: BLE001 -- metering is best-effort by design
            log.warning("llm_meter_failed", task=self._task, error=str(meter_exc)[:200])


def route(row: dict) -> None:
    """Into the current scope's rows (written when it exits), else written now, else (no tenant) one log line."""
    scope = current()
    if scope is not None and row["tenant_id"]:
        scope.rows.append(row)
    elif row["tenant_id"]:
        write_rows([row])
    else:
        log.info(row["kind"], **{k: v for k, v in row.items() if k not in ("tenant_id", "kind")})


def record(kind: str, *, task: str, provider: str | None, model: str | None, input_units: int = 0,
           output_units: int = 0, units: int | None = None, cost_usd: float | None = None, latency_ms: int | None = None, ok: bool = True,
           error_class: str | None = None, tenant_id: str | None = None, module: str | None = None,
           ref_type: str | None = None, ref_id: str | None = None, prompt_version: str | None = None,
           **extra_meta) -> None:
    """One usage_events row for model use outside get_llm().complete(): embeddings, vision, Message Batches results.
    Same shape and routing as an llm_call row (tenant / module / ref from the current scope unless given). Never raises."""
    try:
        scope = current()
        meta = {"task": task, "latency_ms": latency_ms, "ok": ok, "error_class": error_class, "cost_usd": cost_usd,
                "prompt_version": prompt_version or (scope.prompt_version if scope else None), **extra_meta}
        route({
            "tenant_id": str(tenant_id) if tenant_id else (scope.tenant_id if scope else None),
            "module": (module or (scope.module if scope else None) or "llm")[:40],
            "kind": kind,
            "provider": provider,
            "model": model,
            "units": int(units) if units is not None else int(input_units or 0) + int(output_units or 0),
            "input_units": int(input_units or 0) or None,
            "output_units": int(output_units or 0) or None,
            "ref_type": ref_type or (scope.ref_type if scope else None),
            "ref_id": str(ref_id) if ref_id else (scope.ref_id if scope else None),
            "meta": meta,
        })
    except Exception as exc:  # noqa: BLE001 -- metering is best-effort by design
        log.warning("llm_meter_failed", task=task, kind=kind, error=str(exc)[:200])


def answered_by(inner, model: str | None, fallback_used: bool) -> str | None:
    """The provider that produced the answer. The model name settles it (a nested fallback can answer two levels down);
    NIM model ids are org/name."""
    m = (model or "").lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("claude"):
        return "claude"
    if "/" in m:
        return "nvidia"
    node = getattr(inner, "_secondary", None) if fallback_used else inner
    return getattr(node, "provider", None) or getattr(inner, "provider", None)


def cost_usd(provider: str | None, model: str | None, result: dict, ok: bool) -> float | None:
    if provider == "nvidia":
        return 0.0  # NVIDIA NIM free plan
    if not ok:
        return None  # a failed paid call may still be billed; unknown, never guessed
    if provider == "claude":
        from app.adapters.llm.anthropic_claude import PRICES
        from app.adapters.llm.anthropic_claude import cost_usd as claude_cost

        return claude_cost(model, result) if model in PRICES else None
    if provider == "gemini":
        from app.adapters.llm.gemini import cost_usd as gemini_cost

        return gemini_cost(model, int(result.get("input_tokens") or 0), int(result.get("output_tokens") or 0))
    return None


def attempts_cost(atts: list) -> float | None:
    """Sum of every attempt's cost. None when a paid attempt that got a reply has no known price (never guessed)."""
    total = 0.0
    for a in atts:
        if not any(a[k] for k in _TOKEN_KEYS):
            continue   # no reply (error / timeout): nothing billed
        c = cost_usd(a["provider"], a["model"], a, True)
        if c is None:
            return None
        total += c
    return round(total, 6)


def build_row(adapter: MeteredAdapter, result: dict, latency_ms: int, exc: BaseException | None, scope,
              atts: list | None = None) -> dict:
    ok = exc is None
    fallback = bool(result.get("fallback_used"))
    model = result.get("model") or adapter._default_model
    provider = answered_by(adapter.inner, result.get("model"), fallback) if ok else adapter.provider
    if atts:
        inp, out, cache_read, cache_write = (sum(int(a[k] or 0) for a in atts) for k in _TOKEN_KEYS)
        cost, units = attempts_cost(atts), inp + out + cache_read + cache_write
    else:
        inp = int(result.get("input_tokens") or 0)
        out = int(result.get("output_tokens") or 0)
        cache_read = int(result.get("cache_read_input_tokens") or 0)
        cache_write = int(result.get("cache_creation_input_tokens") or 0)
        cost = cost_usd(provider, model, result, ok)
        units = int(result.get("tokens_used") or 0) or inp + out + cache_read + cache_write
    meta = {
        "task": adapter._task,
        "latency_ms": latency_ms,
        "ok": ok,
        "error_class": type(exc).__name__ if exc else None,
        "fallback_used": fallback,
        "cost_usd": cost,
        "prompt_version": scope.prompt_version if scope else None,
    }
    if atts:
        meta.update(attempts=len(atts), attempt_tokens=units)
    if cache_read or cache_write:
        meta.update(cache_read_tokens=cache_read, cache_write_tokens=cache_write)
    return {
        "tenant_id": (scope.tenant_id if scope else None) or adapter._tenant_id,
        "module": ((scope.module if scope else None) or "llm")[:40],
        "kind": "llm_call",
        "provider": provider,
        "model": model,
        "units": units,
        "input_units": inp or None,
        "output_units": out or None,
        "ref_type": scope.ref_type if scope else None,
        "ref_id": scope.ref_id if scope else None,
        "meta": meta,
    }


def _new_session():
    from app.core.database import SessionLocal

    return SessionLocal()


def write_rows(rows: list[dict]) -> None:
    """Insert, commit, close, in one short session. Never raises."""
    try:
        from app.core.database import set_tenant_context
        from app.models.usage_event import UsageEvent

        db = _new_session()
        try:
            for tenant_id, group in groupby(sorted(rows, key=lambda r: r["tenant_id"]), key=lambda r: r["tenant_id"]):
                set_tenant_context(db, tenant_id)
                db.add_all([UsageEvent(**r) for r in group])
                db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 -- metering is best-effort by design
        log.warning("llm_meter_write_failed", rows=len(rows), error=str(exc)[:200])
