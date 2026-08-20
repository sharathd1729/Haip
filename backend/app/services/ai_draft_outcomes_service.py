"""Single write path for AI draft outcomes (HAIP_AI_Autonomy_Plan.md Phase 0,
ticket 1) -- the training signal Phase 3's graduation gate depends on.
Called once per draft, at the moment a human approves (verbatim/edited) or
rejects it. Caller commits, matching core/audit.py's append_audit convention.
"""
import difflib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Message


# Outcomes with a human in the loop. Kept explicit because the verbatim and
# reject *rates* are measures of human review behaviour -- an autonomous send
# has no reviewer and must not sit in those denominators (see migration 082).
HUMAN_REVIEWED_OUTCOMES = ("sent_verbatim", "sent_edited", "rejected")


def record_outcome(
    db: Session,
    tenant_id: str,
    draft: Message,
    outcome: str,
    original_body: Optional[str] = None,
    sent_body: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    intent: Optional[str] = None,
) -> AIDraftOutcome:
    """
    outcome: "sent_verbatim" | "sent_edited" | "rejected" | "sent_autonomous"
    original_body / sent_body: only meaningful for "sent_edited" -- pass the
    pre-edit and post-edit text explicitly rather than reading draft.body,
    since callers typically mutate draft.body to the edited text *before*
    calling this (so it can be committed in the same transaction), which
    would otherwise leave nothing to diff against.
    actor_user_id: the agent who approved/rejected this draft (Phase 2.5,
    HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.4). None for outcomes with
    no human actor ("expired", "sent_autonomous").
    intent: the per-message intent the concierge classified. Previously never
    populated by any caller despite the column existing since migration 058,
    so per-intent accuracy -- the thing the autonomy graduation gate is
    supposed to be decided on -- could not be computed at all.
    """
    edit_distance_pct = None
    if outcome == "sent_edited" and original_body and sent_body is not None:
        # difflib's SequenceMatcher ratio, not true Levenshtein distance --
        # no Levenshtein library is a current dependency and this stdlib
        # ratio serves the same purpose (100 = identical/verbatim, lower =
        # more heavily edited) without adding one.
        ratio = difflib.SequenceMatcher(None, original_body, sent_body).ratio()
        edit_distance_pct = round(ratio * 100, 2)

    now = datetime.now(timezone.utc)
    created_at = draft.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    time_to_action_sec = int((now - created_at).total_seconds()) if created_at else None

    row = AIDraftOutcome(
        tenant_id=tenant_id,
        draft_message_id=draft.id,
        outcome=outcome,
        intent=intent,
        edit_distance_pct=edit_distance_pct,
        time_to_action_sec=time_to_action_sec,
        ai_confidence=draft.ai_confidence,
        # AI Autonomy Plan Phase 1 ticket 4: whatever the bounded grounding
        # loop actually fetched while drafting this message (empty for
        # ungrounded intents, or drafts written before ticket 4 shipped).
        grounded_facts=draft.grounded_facts or [],
        actor_user_id=actor_user_id,
    )
    db.add(row)
    return row
