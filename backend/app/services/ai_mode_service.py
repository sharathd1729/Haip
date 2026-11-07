"""Effective AI concierge mode resolution.

One place decides whether a given conversation's next reply is drafted for a
human, sent autonomously, or suppressed entirely.

Why this exists: the tenant-level mode was previously applied *only* at
conversation-creation time (copied into `conversations.ai_mode`). Changing
the setting therefore did nothing to conversations that already existed --
an owner switching to Autonomous would see every live thread keep drafting
for approval, with no indication why. Resolving at draft time instead makes
the setting mean what the UI says it means.

Precedence:
  1. conversation.ai_mode == "off"  -> off. An agent muting one thread is an
     explicit, per-thread decision and always wins.
  2. tenant.<channel>_ai_mode_default -> the tenant's current policy.

Note the asymmetry is deliberate: a per-conversation "off" overrides the
tenant, but a per-conversation "shadow"/"autonomous" on `ai_mode` does not.
Those values were the stale snapshot taken at creation time, not a decision
anyone made. Since 7 Nov 2026 nothing writes them: the column is NULL unless a
person (Inbox switch), ai_handoff (guest asked for a person) or a read-only
personal-WhatsApp mirror set "off". Old snapshots are cleared by
`clear_derived_modes` (scripts/clear_derived_ai_modes.py). Reports and screens
must show `resolve_mode`, never the raw column.

`Conversation.human_owned` previously forced shadow mode here too, on the
theory that a manual reply or a captured phone number was a real handoff
signal. Reversed by explicit product decision after live reports: nothing
ever reset the flag, so one manual reply (or the guest sharing their phone,
which the bot itself was supposed to keep handling) silently locked a
thread to manual-only approval forever -- contradicting the product's own
"every message gets an autonomous reply" policy. The column and the
call sites that used to set it are gone; do not resurrect this gate without
an explicit decision to do so, and if it comes back, it needs a data
backfill too -- resolve_mode() no longer reads it, so existing rows with
human_owned=True from before this change are not stuck, but a future
gate reading the column again would need those reset first.
"""

from __future__ import annotations

from typing import Optional, Tuple

import structlog

log = structlog.get_logger()

VALID_MODES = ("off", "shadow", "autonomous")
DEFAULT_MODE = "shadow"
DEFAULT_THRESHOLD = 0.78

# Channel value on Conversation.channel -> tenant column prefix
_CHANNEL_PREFIX = {
    "whatsapp": "wa",
    "instagram": "ig",
}


def _channel_key(channel) -> Optional[str]:
    raw = getattr(channel, "value", channel)
    if raw is None:
        return None
    return _CHANNEL_PREFIX.get(str(raw).lower())


def resolve_mode(tenant, conversation) -> str:
    """Effective mode for this conversation's next AI reply."""
    # Emergency stop wins over everything. Downgrades to shadow rather than
    # off deliberately: the owner pulling this wants the AI to stop talking
    # to guests, not to lose the drafting assist their agents are using.
    if tenant is not None and getattr(tenant, "ai_kill_switch", False):
        return "shadow"

    if conversation is not None and (conversation.ai_mode or "").lower() == "off":
        return "off"

    prefix = _channel_key(getattr(conversation, "channel", None))
    if prefix is None or tenant is None:
        # Unknown channel (webchat, email) has no tenant policy column; fall
        # back to whatever the conversation carries, then to shadow. Never
        # default an unknown channel to autonomous.
        mode = (getattr(conversation, "ai_mode", None) or DEFAULT_MODE).lower()
        return mode if mode in VALID_MODES else DEFAULT_MODE

    mode = (getattr(tenant, f"{prefix}_ai_mode_default", None) or DEFAULT_MODE).lower()
    return mode if mode in VALID_MODES else DEFAULT_MODE


def resolve_threshold(tenant, conversation, fallback: float = DEFAULT_THRESHOLD) -> float:
    """Confidence floor for autonomous sending on this conversation's channel.

    Previously concierge_draft.py read `ig_ai_confidence_threshold` for every
    channel, so a WhatsApp tenant's autonomy threshold was governed by their
    Instagram setting.
    """
    prefix = _channel_key(getattr(conversation, "channel", None))
    if prefix is None or tenant is None:
        return fallback
    val = getattr(tenant, f"{prefix}_ai_confidence_threshold", None)
    return float(val) if val is not None else fallback


def resolve(tenant, conversation) -> Tuple[str, float]:
    return resolve_mode(tenant, conversation), resolve_threshold(tenant, conversation)


def clear_derived_modes(db, tenant_id: str, *, apply: bool) -> dict:
    """Backfill: NULL every stored ai_mode on this tenant's conversations that is not a per-thread "off".

    Those rows hold the creation-time copy of the workspace setting (1,141 "shadow" rows on Ratha, 7 Nov 2026) and mislead
    anything reading the column. "off" (any case) is a real override and is never touched. Returns {stored value: rows}
    for what is (or, on a dry run, would be) cleared. Idempotent: a second run finds nothing. The caller commits.
    """
    from sqlalchemy import func
    from app.models.conversation import Conversation

    q = db.query(Conversation).filter(
        Conversation.tenant_id == tenant_id,
        Conversation.ai_mode.isnot(None),
        func.lower(Conversation.ai_mode) != "off",
    )
    counts = {str(v): int(n) for v, n in q.with_entities(Conversation.ai_mode, func.count()).group_by(Conversation.ai_mode)}
    if apply and counts:
        q.update({Conversation.ai_mode: None}, synchronize_session=False)
        log.info("ai_mode_derived_cleared", tenant_id=tenant_id, rows=sum(counts.values()))
    return counts
