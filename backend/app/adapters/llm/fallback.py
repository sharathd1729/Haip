"""
FallbackAdapter -- try a primary LLM adapter, and if it errors or times out,
retry the same request once on a secondary adapter.

Why this exists: internal analysis (call scoring, wrap-up, lead summaries)
runs on NVIDIA NIM, which has repeatedly gone into multi-hour stretches of
HTTP 504s / hangs (see the notes in adapters/llm/__init__.py). Nothing fell
back, so calls sat at "pending" and Leads360 cards lost their AI summary until
NIM recovered. The OpenAI SDK's own timeout is 10 minutes, so a hung request
never even raised -- the primary attempt is therefore bounded here.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import Optional

from app.adapters.llm.base import LLMAdapter

log = structlog.get_logger()


class FallbackAdapter(LLMAdapter):
    def __init__(
        self,
        primary: LLMAdapter,
        secondary: LLMAdapter,
        task: str,
        primary_timeout: float,
    ):
        self._primary = primary
        self._secondary = secondary
        self._task = task
        self._primary_timeout = primary_timeout
        # Callers read adapter.provider to pick provider-specific behaviour;
        # it keeps describing the route's primary provider.
        self.provider = getattr(primary, "provider", None)

    @property
    def _default_model(self):
        # Same reason: the routed model is the primary's.
        return getattr(self._primary, "_default_model", None)

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        tools: Optional[list] = None,
        **kwargs,
    ) -> dict:
        try:
            return await asyncio.wait_for(
                self._primary.complete(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    model=model,
                    max_tokens=max_tokens,
                    tools=tools,
                    **kwargs,
                ),
                timeout=self._primary_timeout,
            )
        except Exception as primary_exc:  # CancelledError is not an Exception: it still propagates
            log.warning(
                "llm_primary_failed_using_fallback",
                task=self._task,
                primary=getattr(self._primary, "provider", None),
                fallback=getattr(self._secondary, "provider", None),
                error=repr(primary_exc)[:300],
                timed_out=isinstance(primary_exc, asyncio.TimeoutError),
            )
            try:
                # No `model` and no provider-specific kwargs (thinking=...):
                # both name things only the primary provider understands, so
                # the secondary uses its own routed default.
                result = await self._secondary.complete(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    max_tokens=max_tokens,
                    tools=tools,
                )
            except Exception as secondary_exc:
                log.error(
                    "llm_fallback_also_failed",
                    task=self._task,
                    primary_error=repr(primary_exc)[:200],
                    fallback_error=repr(secondary_exc)[:200],
                )
                # The primary's failure is the root cause the retry machinery
                # (Celery retries, DLQ) should see.
                raise primary_exc from secondary_exc
            if isinstance(result, dict):
                result["fallback_used"] = True
            log.info("llm_fallback_succeeded", task=self._task)
            return result
