"""Detect when a guest wants a human, and hand over the tenant's contact details.

The Instagram quick-reply rule already covers this for a fixed keyword list,
but it *replaces* the AI reply rather than adding to it -- so "what's the
price, and can you call me?" got the canned contact block and never had the
price question answered. It is also literal: "can someone ring me" or
"let's talk on wa" match none of the configured keywords, and the AI has no
knowledge of the phone number, so the guest is left with no way to reach
anyone.

This runs alongside the AI instead: the model answers the question, and when
the guest asked for a call or WhatsApp the contact block is appended to that
answer.

Deliberately keyword-based rather than another LLM call. Handoff intent is a
narrow, high-frequency signal on a latency-sensitive path, and a wrong answer
is expensive in both directions -- a missed handoff loses the lead, a false
positive pastes a phone number onto an unrelated reply.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Phrases that mean "put me through to a person". Matched on word boundaries
# so "callback" does not trip "call" twice and "number" does not match inside
# another word.
_CALL_PATTERNS = (
    r"\bcall\b", r"\bcall me\b", r"\bring me\b", r"\bring\b", r"\bphone\b",
    r"\bcontact number\b", r"\bmobile\b", r"\bnumber\b", r"\bcall back\b",
    r"\bcallback\b",
)

# "I want to talk to someone" asks for a human without naming a channel.
# Treating these as call-only would hand over a phone number to a guest who
# may have meant WhatsApp, so an ambiguous ask offers whatever is configured.
_AMBIGUOUS_PATTERNS = (
    r"\btalk\b", r"\bspeak\b", r"\bconnect\b", r"\breach you\b",
    r"\bget in touch\b", r"\bcontact you\b",
)
_WHATSAPP_PATTERNS = (
    r"\bwhatsapp\b", r"\bwhats app\b", r"\bwtsp\b", r"\bwsp\b", r"\bwa\b",
    r"\bwhtsapp\b", r"\bwhatsup\b",
)

# Guards against the commonest false positives. "call" appears constantly in
# hospitality copy that is not a handoff request ("what do you call it",
# "calls for a celebration"), and a guest reciting their own number is giving
# a detail, not asking for ours.
_NEGATIVE_PATTERNS = (
    r"\bwhat do you call\b", r"\bwhat is it called\b", r"\bwhat's it called\b",
    r"\bcalls for\b", r"\bso called\b", r"\bcalled\b",
)


@dataclass(frozen=True)
class HandoffIntent:
    wants_call: bool
    wants_whatsapp: bool

    @property
    def wanted(self) -> bool:
        return self.wants_call or self.wants_whatsapp


def detect_handoff_intent(text: Optional[str]) -> HandoffIntent:
    """Does this message ask to be called, or to move to WhatsApp?"""
    if not text or not text.strip():
        return HandoffIntent(False, False)

    lowered = text.lower()
    if any(re.search(p, lowered) for p in _NEGATIVE_PATTERNS):
        return HandoffIntent(False, False)

    wants_call = any(re.search(p, lowered) for p in _CALL_PATTERNS)
    wants_whatsapp = any(re.search(p, lowered) for p in _WHATSAPP_PATTERNS)

    # Channel named explicitly -- honour exactly that.
    if wants_call or wants_whatsapp:
        return HandoffIntent(wants_call, wants_whatsapp)

    # Otherwise: asked for a human without saying how. Flag both so the guest
    # is offered every route available rather than being guessed at.
    if any(re.search(p, lowered) for p in _AMBIGUOUS_PATTERNS):
        return HandoffIntent(True, True)

    return HandoffIntent(False, False)


def build_handoff_block(tenant, intent: HandoffIntent) -> str:
    """The contact lines to append to an AI reply, or "" when there is
    nothing to offer.

    Returns only what the guest actually asked for: someone asking for
    WhatsApp gets the WhatsApp link, not a phone number they did not want.
    When the request is ambiguous ("can I connect with someone") both are
    offered, since guessing wrong costs the lead.
    """
    if not intent.wanted:
        return ""
    if not getattr(tenant, "handoff_enabled", True):
        return ""

    phone = (getattr(tenant, "handoff_phone", None) or "").strip()
    wa_url = (getattr(tenant, "handoff_whatsapp_url", None) or "").strip()
    if not phone and not wa_url:
        return ""

    # An explicit single-channel ask gets that channel only; anything else
    # gets whatever is configured.
    only_whatsapp = intent.wants_whatsapp and not intent.wants_call
    only_call = intent.wants_call and not intent.wants_whatsapp

    lines = []
    if phone and not only_whatsapp:
        lines.append(f"Call us on {phone}")
    if wa_url and not only_call:
        lines.append(f"WhatsApp us at {wa_url}")

    if not lines:
        # Asked for the one channel that is not configured -- offer the other
        # rather than staying silent about how to reach anyone.
        if phone:
            lines.append(f"Call us on {phone}")
        elif wa_url:
            lines.append(f"WhatsApp us at {wa_url}")

    return " · ".join(lines)


def build_offer_block(tenant) -> str:
    """The choice offered up front, before anyone asks.

    Most leads never say "call me" outright -- they just go quiet. Waiting
    for explicit intent therefore misses the ones who would happily have
    phoned, so the first reply in a thread states both routes: keep chatting
    here, or reach a human now.

    Offered once per conversation (the caller decides when); repeating it on
    every reply reads as a bot trying to get rid of you.
    """
    if not getattr(tenant, "handoff_enabled", True):
        return ""

    phone = (getattr(tenant, "handoff_phone", None) or "").strip()
    wa_url = (getattr(tenant, "handoff_whatsapp_url", None) or "").strip()
    if not phone and not wa_url:
        return ""

    routes = []
    if phone:
        routes.append(f"call {phone}")
    if wa_url:
        routes.append(f"WhatsApp {wa_url}")

    return (
        "Happy to answer anything right here — or if you'd rather speak to "
        f"someone now, {' or '.join(routes)}."
    )


def append_offer(reply: str, tenant) -> str:
    """Append the up-front choice to a first reply, avoiding duplication."""
    block = build_offer_block(tenant)
    if not block:
        return reply

    body = (reply or "").rstrip()
    if not body:
        return block

    phone = (getattr(tenant, "handoff_phone", None) or "").strip()
    wa_url = (getattr(tenant, "handoff_whatsapp_url", None) or "").strip()
    if (phone and phone in body) or (wa_url and wa_url in body):
        return body

    return f"{body}\n\n{block}"


def append_handoff(reply: str, tenant, text: Optional[str]) -> tuple[str, HandoffIntent]:
    """Append the contact block to `reply` when `text` asks for a human.

    Returns (possibly_extended_reply, intent) so callers can record that a
    handoff was offered without re-running the detection.
    """
    intent = detect_handoff_intent(text)
    block = build_handoff_block(tenant, intent)
    if not block:
        return reply, intent

    body = (reply or "").rstrip()
    if not body:
        return block, intent
    # Never duplicate details the model already volunteered.
    phone = (getattr(tenant, "handoff_phone", None) or "").strip()
    wa_url = (getattr(tenant, "handoff_whatsapp_url", None) or "").strip()
    if (phone and phone in body) or (wa_url and wa_url in body):
        return body, intent

    return f"{body}\n\n{block}", intent
