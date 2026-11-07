"""Who an LLM call is for: tenant, module, record and prompt version, carried across awaits by a contextvar.

    with llm_scope(tenant_id=..., module="concierge", ref_type="message", ref_id=..., prompt_version="concierge-reply-v20"):
        ...  # every get_llm(task).complete() in here is metered against this scope

A nested scope inherits what it does not set and shares the outer scope's rows. Rows are kept in memory and written ONCE,
in one short session, when the OUTERMOST scope exits: no database connection is opened while an LLM call runs, and
`scoped_task` puts that write after the Celery task's own session has closed (so it reuses the released pooled connection).
asyncio tasks copy the context when they are created (run_until_complete, asyncio.run), so a scope set in a sync Celery task
is seen by the coroutine, and the rows list is the same object on both sides.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import inspect
from dataclasses import dataclass, field, replace


@dataclass
class LLMScope:
    tenant_id: str | None = None
    module: str | None = None
    ref_type: str | None = None
    ref_id: str | None = None
    prompt_version: str | None = None
    rows: list = field(default_factory=list)  # shared with nested scopes; the outermost scope writes them


_current: contextvars.ContextVar[LLMScope | None] = contextvars.ContextVar("llm_scope", default=None)


def current() -> LLMScope | None:
    return _current.get()


@contextlib.contextmanager
def llm_scope(**fields):
    parent = _current.get()
    given = {k: (str(v) if k in ("tenant_id", "ref_id") else v) for k, v in fields.items() if v is not None}
    scope = replace(parent, **given) if parent is not None else LLMScope(**given)  # replace keeps the same rows list
    token = _current.set(scope)
    try:
        yield scope
    finally:
        _current.reset(token)
        if parent is None and scope.rows:
            from app.adapters.llm import metered

            metered.write_rows(scope.rows)


def scoped_task(module: str, ref_type: str | None = None, ref_arg: str | None = None, prompt_key: str | None = None):
    """Put under @celery_app.task: the whole task runs in a scope (tenant from its `tenant_id` argument), so the meter rows
    are written after the task's `finally: db.close()`."""

    def deco(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                bound = sig.bind_partial(*args, **kwargs).arguments
            except TypeError:
                bound = {}
            from app.core.prompt_versions import get_version

            with llm_scope(
                tenant_id=bound.get("tenant_id"),
                module=module,
                ref_type=ref_type,
                ref_id=bound.get(ref_arg) if ref_arg else None,
                prompt_version=get_version(prompt_key) if prompt_key else None,
            ):
                return fn(*args, **kwargs)

        wrapper.__signature__ = sig  # Celery's argument check (getfullargspec) reads this, not __wrapped__
        return wrapper

    return deco
