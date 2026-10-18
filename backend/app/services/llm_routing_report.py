"""Which model actually answers this tenant's guests -- read from the router, never from a copy. No secrets, no network calls.

Used by GET /ai/routing (owner) and scripts/diagnose_llm_routing.py. Keys are reported as present / absent only.

Facts this report makes visible (Oct 2026):
  * the guest reply (``concierge_draft``) follows _TASK_ROUTES; the message understanding before it (``quick_classify``) is a
    separate NVIDIA call with a Gemini retry;
  * ``tenants.llm_provider_override`` is read by get_llm(task, tenant_id) only, and no call site passes tenant_id, so a value
    stored there changes nothing today (``override_applied`` is therefore always False). If it were wired, it would also drop the
    routed model (the provider's class default is used), so it is reported, not applied;
  * a provider failure or timeout on the reply is retried once and then becomes the holding reply ("Let me check and get right
    back to you"), forced to human review -- it never falls back to another provider.
"""
from __future__ import annotations

from typing import Optional

from app.core.config import settings

# Guest-facing first, then what feeds or follows it.
TASKS = (
    ("concierge_draft", "Guest reply on WhatsApp and Instagram (the AI concierge draft / autonomous send)"),
    ("quick_classify", "Reading the guest's message before the reply: intent, dates, party, destination"),
    ("concierge_rewrite", "Rewrite / translate a draft or the composer text on request"),
    ("lead_summary", "Lead summary and analysis on the lead card"),
)


def _key(name: str) -> str:
    return "present" if getattr(settings, name, "") else "absent"


def report(tenant=None) -> dict:
    from app.adapters.llm import _GEMINI_FALLBACK_TASKS, _TASK_ROUTES
    from app.workers.tasks.concierge_draft import MAX_REPLY_ATTEMPTS, MAX_REPLY_SECONDS_BY_PROVIDER, MAX_REPLY_SECONDS_DEFAULT
    override: Optional[str] = getattr(tenant, "llm_provider_override", None) if tenant is not None else None
    rows = []
    for task, purpose in TASKS:
        provider, model = _TASK_ROUTES.get(task) or _TASK_ROUTES["fallback"]
        fb = _GEMINI_FALLBACK_TASKS.get(task)
        rows.append({
            "task": task, "purpose": purpose, "provider": provider, "model": model,
            "gemini_fallback_after_seconds": fb if (fb is not None and provider == "nvidia") else None,
            "gemini_fallback_active": bool(fb is not None and provider == "nvidia" and settings.GEMINI_API_KEY),
            "timeout_seconds": (MAX_REPLY_SECONDS_BY_PROVIDER.get(provider, MAX_REPLY_SECONDS_DEFAULT) if task == "concierge_draft" else None),
        })
    reply = rows[0]
    gemini_needed = reply["provider"] == "gemini"
    return {
        "tasks": rows,
        "tenant_override": override or None,
        "override_applied": False,
        "override_note": ("A provider override is stored for this workspace but no AI call passes the workspace to the router, so it "
                          "is not used." if override else None),
        "keys": {"GEMINI_API_KEY": _key("GEMINI_API_KEY"), "NVIDIA_API_KEY": _key("NVIDIA_API_KEY"), "LLM_PROVIDER": settings.LLM_PROVIDER or None},
        "guest_reply": {
            "provider": reply["provider"], "model": reply["model"], "attempts": MAX_REPLY_ATTEMPTS,
            "timeout_seconds": reply["timeout_seconds"],
            "on_failure": "holding reply 'Thanks for your message! Let me check and get right back to you.' held for a person; "
                          "no other provider is tried",
            "will_fail": gemini_needed and not settings.GEMINI_API_KEY,
        },
        "channels": {
            "whatsapp": "concierge_draft (above), mode from the WhatsApp AI setting",
            "instagram": "concierge_draft (above), mode from the Instagram AI setting",
            "personal_whatsapp": "no AI: mirrored chats never trigger a draft (read-only bridge)",
        },
    }
