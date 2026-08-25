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
    # v2 on these four (AI Autonomy Plan Phase 0 ticket 2): the tool-calling
    # contract that shapes each task's output changed from a hand-written
    # provider-specific dialect to the canonical ToolSpec shape rendered
    # per-provider by adapters/llm/tools.py -- same semantic fields, but the
    # code path producing a stored/logged result is genuinely different now.
    "call_classify":   "call-classify-v2",      # classify.jinja
    "call_judge":      "call-judge-v2",         # judge.jinja
    "call_wrap_up":    "call-wrap-up-v3",       # wrap_up.jinja
    # v3 (AI Autonomy Plan Phase 1 ticket 4): concierge_reply.jinja now
    # renders a grounded_facts section (real availability/pricing from the
    # bounded tool loop) instead of the always-empty kb_snippets it relied
    # on before.
    # v4 (AI Autonomy Plan Phase 2): renders a tone instruction -- fixes
    # AIDraftPanel's tone chips, which were fully wired UI with no effect on
    # the actual draft (the frontend never sent the selection at all).
    # v5 (HAIP Inbox UI-fidelity pass, ticket 3): renders a guest_missing_phone
    # instruction so the draft naturally asks for a phone number when the
    # guest's profile has none on file yet.
    # v6 (2026-08-20): pricing is never disclosed in chat. The concierge
    # qualifies the lead (name/dates/guests/property/requests) and hands off
    # to a human agent who negotiates personally; price figures are redacted
    # out of grounded_facts before rendering so the model never sees a number
    # it could repeat. Replies also tightened to <45 words and explicitly
    # de-assistant-ified (no "Thank you for reaching out", no lists).
    # v7 (2026-08-22): the "WHAT WE STILL NEED FROM THIS LEAD" block had no
    # guard tying it to the guest's actual question, unlike the pricing rule
    # above it ("When the guest asks about cost..."). Every reply -- "Hi",
    # "Routes?", a real price question -- got the identical qualification
    # script, so factual questions the knowledge base could answer (routes,
    # amenities, policies) never got answered. Now explicitly secondary:
    # answer from KB/live availability first, weave in a missing-detail ask
    # only if it fits, never as a substitute for answering.
    # v8 (2026-08-22): v7's "weave in if it fits" still wasn't enough --
    # a guest asking about an internship got asked for "preferred travel
    # dates" in the same breath. The qualification block now explicitly
    # recognises off-topic messages (jobs/careers, press, spam -- nothing to
    # do with booking a stay) and skips the travel ask entirely, handing
    # off to a human instead of forcing every reply into the booking funnel.
    # v9: capacity claims ("up to N guests", "sleeps N") now must trace to
    # a real max_adults value from LIVE AVAILABILITY -- a guest asking
    # about a 20-person group was told "designed for up to 4 guests" (the
    # real capacity is 8), a pure hallucination since the prompt never
    # rendered a capacity figure at all before this. See
    # concierge_draft.py's _check_grounding()/_CAPACITY_RE.
    "concierge_reply": "concierge-reply-v10",   # concierge_reply.jinja
    "lost_reason":     "lost-reason-v1",        # lost_reason.jinja
    "agent_performance_narrative": "agent-performance-narrative-v1",  # agent_performance_narrative.jinja

    # Inline prompts built in Python
    "leads360_summary":       "leads360-summary-v2",  # generate_ai_summary.py
    "ask_haip_intent":        "ask-haip-intent-v1",
    "ask_haip_rca":           "ask-haip-rca-v1",
    "ask_haip_report":        "ask-haip-report-v1",
    "ask_haip_freeform_sql":  "ask-haip-freeform-sql-v1",
    "ask_haip_freeform_summary": "ask-haip-freeform-summary-v1",
    # AI Autonomy Plan Phase 1 ticket 4: new intent classify+extract step
    # gating the grounded tool loop.
    "concierge_intent": "concierge-intent-v1",
    # HAIP Inbox prototype-wiring plan, ticket 3: real translate/tone-fix
    # rewrite of an existing pending AI draft.
    "concierge_rewrite": "concierge-rewrite-v1",
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
