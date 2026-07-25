"""
Central registry of prompt versions.

CLAUDE.md requires a version bump on every prompt content change, so that a
stored AI result can always be traced back to the prompt that produced it.
Before this module only one of eleven LLM call sites did that
(generate_ai_summary's module-level PROMPT_VERSION), and none of the Jinja
templates in app/prompts/ were versioned at all — so for most AI output there
was no way to tell which prompt generated it.

Deliberately a plain dict of constants rather than a database table: a prompt
version is a property of the code, not of tenant data. Reading it must never
cost a query, and it must stay reviewable in the same diff that changes the
prompt text.

## Bumping

When you change a prompt's content — the Jinja template or the inline string —
bump its version here in the same commit. Use `<name>-v<n>`.

## Adding a prompt

Add the key here, then pass it to `stamp()` at the call site so the version
lands in that task's structured log line.
"""
from typing import Any, Optional

# prompt key -> current version. Keys are stable identifiers; values change.
PROMPT_VERSIONS: dict[str, str] = {
    # Jinja templates in app/prompts/
    "call_classify":   "call-classify-v1",      # classify.jinja
    "call_judge":      "call-judge-v1",         # judge.jinja
    "call_wrap_up":    "call-wrap-up-v1",       # wrap_up.jinja
    "concierge_reply": "concierge-reply-v1",    # concierge_reply.jinja
    "lost_reason":     "lost-reason-v1",        # lost_reason.jinja

    # Inline prompts built in Python
    "leads360_summary":       "leads360-summary-v2",  # generate_ai_summary.py
    "ask_haip_intent":        "ask-haip-intent-v1",
    "ask_haip_rca":           "ask-haip-rca-v1",
    "ask_haip_report":        "ask-haip-report-v1",
    "ask_haip_freeform_sql":  "ask-haip-freeform-sql-v1",
    "ask_haip_freeform_summary": "ask-haip-freeform-summary-v1",
}

UNKNOWN = "unregistered"


def get_version(prompt_key: str) -> str:
    """
    Current version for a prompt key.

    Returns "unregistered" rather than raising for an unknown key: a missing
    registry entry is a bookkeeping problem, and must never take down the AI
    task that was trying to log it.
    """
    return PROMPT_VERSIONS.get(prompt_key, UNKNOWN)


def stamp(prompt_key: str, model: Optional[str] = None, **extra: Any) -> dict[str, Any]:
    """
    Build the provenance fields for a structured log line or audit payload.

        log.info("call_classified", call_id=call.id, **stamp("call_classify", model))

    Keeping this in one helper means every AI call site emits the same field
    names, so results stay filterable by prompt version across all of them.
    """
    meta: dict[str, Any] = {"prompt_key": prompt_key, "prompt_version": get_version(prompt_key)}
    if model:
        meta["model"] = model
    meta.update(extra)
    return meta
