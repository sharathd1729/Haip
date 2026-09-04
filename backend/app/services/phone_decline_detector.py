"""Phone-decline detector — guests who explicitly refuse to share a phone
number and ask to be helped in the DM itself.

Distinct from escalation_policy.py: a declined phone number is not a
safety/legal/billing risk the AI must never touch, so this does NOT force
the draft to human review or block the autonomous send (the AI can still
answer the guest's actual question fine, as confirmed live at 95%
confidence for real guests who did exactly this). It's an ADDITIONAL signal
that a human should personally follow up in the DM, alongside whatever the
AI already sent -- same "the AI still answers, a human still gets a task"
shape as _maybe_create_price_handoff in concierge_draft.py, which this is
usually paired with (a guest declining a number is very often also asking
about price).

Deliberately keyword-based, checked against the guest's own words, not the
AI's draft or its free-text needs_human reason -- same reasoning as
escalation_policy.py: the model's own phrasing of "why" varies message to
message and isn't reliable to pattern-match on, but what the guest actually
typed is stable.
"""

from __future__ import annotations

import re
from typing import Optional

# Phrases that reference a phone/number refusal directly -- deliberately NOT
# including generic phrases like "reply here itself" or "kindly give me the
# details" on their own (both confirmed live in the same real message as "no
# phone number", but neither implies a phone decline without that context,
# and firing on them alone would be noisy enough to train agents to ignore
# the alert).
_PHRASES: tuple[str, ...] = (
    "no phone number", "no phone no", "dont have a number", "don't have a number",
    "dont have a phone", "don't have a phone",
    "not comfortable sharing my number", "not comfortable sharing my phone",
    "wont share my number", "won't share my number",
    "rather not share my number", "rather not give my number",
    "prefer not to share my number", "cant share my number", "can't share my number",
    "not share my number", "not give my number", "not give you my number",
    "no need for phone number", "skip the phone number", "without sharing my number",
)

_COMPILED: list[tuple[str, re.Pattern]] = [
    (p, re.compile(re.escape(p), re.IGNORECASE)) for p in _PHRASES
]


def detect_phone_decline(text: str) -> Optional[str]:
    """Return the matched phrase, or None. `text` is the guest's own words
    (e.g. concierge_draft.py's burst_text), never the AI's draft."""
    if not text or not text.strip():
        return None
    lowered = text.lower()
    for phrase, pattern in _COMPILED:
        if pattern.search(lowered):
            return phrase
    return None


# Single source of truth for the "Guest declined phone number" title-prefix
# match -- concierge_draft.py's own dedup check and conversations.py's
# list/detail flags each re-implement this filter inline; the report emails
# below (daily_report_service.py, agent_worklist_email.py) use this instead
# of a fourth copy.
_TASK_TITLE_PREFIX = "Guest declined phone number%"


def open_tasks(db, tenant_id: str, *, agent_id: "str | None" = None) -> list[dict]:
    """Open phone-decline Tasks for this tenant, each carrying enough to
    link straight to the guest's Profile 360 page. Pass `agent_id` to scope
    to one agent's assigned conversations (their own worklist/EOD report),
    omit it for the tenant-wide standing backlog (the owner report)."""
    from app.models.task import Task
    from app.models.conversation import Conversation
    from app.models.guest import Guest

    q = (
        db.query(Task, Guest.name)
        .join(Conversation, Task.conversation_id == Conversation.id)
        .outerjoin(Guest, Task.guest_id == Guest.id)
        .filter(
            Task.tenant_id == tenant_id,
            Task.is_done.is_(False),
            Task.title.ilike(_TASK_TITLE_PREFIX),
        )
    )
    if agent_id:
        q = q.filter(Conversation.assigned_to == agent_id)

    return [
        {
            "task_id": task.id,
            "conversation_id": task.conversation_id,
            "guest_id": task.guest_id,
            "guest_name": guest_name or "Unnamed lead",
        }
        for task, guest_name in q.order_by(Task.created_at.desc()).all()
    ]
