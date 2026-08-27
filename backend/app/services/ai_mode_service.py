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
  2. conversation.human_owned == True -> shadow. A human agent has sent (or
     approved) at least one reply in this thread -- a real, programmatic
     decision, not a stale snapshot -- so the bot stops auto-sending but
     keeps drafting suggestions.
  3. tenant.<channel>_ai_mode_default -> the tenant's current policy.

Note the asymmetry is deliberate: a per-conversation "off" overrides the
tenant, but a per-conversation "shadow"/"autonomous" on `ai_mode` does not.
Those values are almost always just the stale snapshot taken at creation
time, not a decision anyone made -- human_owned is the real signal for
"someone is actively handling this."
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

    if conversation is not None and getattr(conversation, "human_owned", False):
        return "shadow"

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
