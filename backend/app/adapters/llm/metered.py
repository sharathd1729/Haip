"""MeteredAdapter: one `usage_events` row (kind="llm_call") per get_llm(task).complete() call. Numbers and labels only, never
the prompt or the output text.

It wraps whatever get_llm() built (the routed adapter, the NVIDIA->Gemini FallbackAdapter or the LLM_FORCE_PROVIDER=claude
FallbackAdapter), so a fallback is ONE call and ONE row, with the provider that actually answered. Arguments go to the inner
adapter exactly as given (provider-specific kwargs such as thinking= included), the result comes back unchanged and an
exception is re-raised unchanged. Metering never breaks the work it measures: every error in here is logged and swallowed.

Where the row goes (adapters/llm/scope.py): inside a scope, into the scope's rows, written when the outermost scope exits;
no scope but get_llm() was given a tenant_id: written now in its own short session; no tenant at all: one structured
`llm_call` log line instead (usage_events.tenant_id is NOT NULL). Cost reports read kind="llm_call" only; the Studio's older
`llm_tokens` rows (usage_service.record_llm) stay as they are, so nothing is counted twice.
"""

from __future__ import annotations

import time
from itertools import groupby

import structlog

from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.scope import current

log = structlog.get_logger()


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
        start = time.monotonic()
        try:
            result = await self.inner.complete(*args, **kwargs)
        except BaseException as exc:  # a timeout cancels the call (CancelledError): it is still a failed call to count
            self._meter(None, start, exc)
            raise
        self._meter(result, start, None)
        return result

    def _meter(self, result, start: float, exc: BaseException | None) -> None:
        try:
            scope = current()
            row = build_row(
                self, result if isinstance(result, dict) else {}, int((time.monotonic() - start) * 1000), exc, scope
            )
            if scope is not None and row["tenant_id"]:
                scope.rows.append(row)
            elif row["tenant_id"]:
                write_rows([row])
            else:
                log.info("llm_call", **{k: v for k, v in row.items() if k != "tenant_id"})
        except Exception as meter_exc:  # noqa: BLE001 -- metering is best-effort by design
            log.warning("llm_meter_failed", task=self._task, error=str(meter_exc)[:200])


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


def build_row(adapter: MeteredAdapter, result: dict, latency_ms: int, exc: BaseException | None, scope) -> dict:
    ok = exc is None
    fallback = bool(result.get("fallback_used"))
    model = result.get("model") or adapter._default_model
    provider = answered_by(adapter.inner, result.get("model"), fallback) if ok else adapter.provider
    inp = int(result.get("input_tokens") or 0)
    out = int(result.get("output_tokens") or 0)
    cache_read = int(result.get("cache_read_input_tokens") or 0)
    cache_write = int(result.get("cache_creation_input_tokens") or 0)
    meta = {
        "task": adapter._task,
        "latency_ms": latency_ms,
        "ok": ok,
        "error_class": type(exc).__name__ if exc else None,
        "fallback_used": fallback,
        "cost_usd": cost_usd(provider, model, result, ok),
        "prompt_version": scope.prompt_version if scope else None,
    }
    if cache_read or cache_write:
        meta.update(cache_read_tokens=cache_read, cache_write_tokens=cache_write)
    return {
        "tenant_id": (scope.tenant_id if scope else None) or adapter._tenant_id,
        "module": ((scope.module if scope else None) or "llm")[:40],
        "kind": "llm_call",
        "provider": provider,
        "model": model,
        "units": int(result.get("tokens_used") or 0) or inp + out + cache_read + cache_write,
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
