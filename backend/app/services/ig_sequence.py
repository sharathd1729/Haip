"""Follow-up messages after an Instagram automation's final message (Instagram Automations v2, phase 3).

`action_config.sequence` holds up to 3 steps, each sent `after_minutes` after the previous message. A step goes out only
while it still makes sense: nobody has written since the sequence started (the guest, a team member, the AI), no DM form
is running for them, they haven't said STOP, the hourly caps allow it, and Instagram's 24-hour window since the guest's
last message is still open. Otherwise the sequence stops and says why in ig_automation_events.

No table: each step is a Celery countdown task carrying the sequence's start time (same pattern as the one follow-up).
A sequence starts only where the chat is open (after a tap, a DM form, or an open-chat trigger), never after a
comment's private reply alone: Instagram allows nothing more until the person writes back.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.services import ig_automation as engine

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=23)


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def steps(rule: AutomationRule) -> list[dict]:
    return list((rule.action_config or {}).get("sequence") or [])


def _queue(
    tenant_id, rule_id, guest_id, conversation_id, recipient_id, step: int, started_at: str, minutes: int
) -> None:
    try:
        from app.workers.tasks.ig_sequence_step import send_step

        send_step.apply_async(
            args=[tenant_id, rule_id, guest_id, conversation_id, recipient_id, step, started_at],
            countdown=max(60, int(minutes) * 60),
        )
    except Exception as exc:  # noqa: BLE001 -- a queue outage only loses the follow-ups
        logger.warning("ig_sequence_not_queued rule=%s: %s", rule_id, exc)


def begin(
    rule: AutomationRule, tenant_id: str, *, recipient_id: str, guest_id: str | None, conversation_id: str | None
) -> bool:
    """Queue the first follow-up, timed from now (the final message just went out). True when queued."""
    plan = steps(rule)
    if not plan or not guest_id or not conversation_id:
        return False
    _queue(
        tenant_id,
        rule.id,
        guest_id,
        conversation_id,
        recipient_id,
        0,
        datetime.now(UTC).isoformat(),
        plan[0].get("after_minutes") or 60,
    )
    return True


def _stop_reason(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    guest_id: str,
    conversation_id: str,
    since: datetime,
    now: datetime,
) -> str | None:
    from app.models.conversation import Message, MessageDirection
    from app.services import ig_dm_form

    if (
        db.query(Message.id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.INBOUND,
            Message.created_at > since,
        )
        .first()
    ):
        return "guest_replied"
    someone = (
        db.query(Message.id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at > since,
            (Message.sender_kind.is_(None)) | (Message.sender_kind != "automation"),
        )
        .first()
    )
    if someone:
        return "someone_answered"
    if ig_dm_form.active_session(db, tenant_id, guest_id) is not None:
        return "form_running"
    reason = engine.skip_reason(db, tenant_id, rule, guest_id, starting=False)
    if reason:
        return reason
    last_in = (
        db.query(func.max(Message.created_at))
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.INBOUND,
        )
        .scalar()
    )
    if now > (_aware(last_in) or since) + WINDOW:
        return "window_closed"
    return None


def send_step(
    db: Session,
    tenant_id: str,
    rule_id: str,
    guest_id: str,
    conversation_id: str,
    recipient_id: str,
    step: int,
    started_at: str,
) -> str:
    """Send follow-up `step` if it still makes sense, then queue the next. Returns what happened. Commits."""
    rule = db.query(AutomationRule).filter_by(id=rule_id, tenant_id=tenant_id).first()
    plan = steps(rule) if rule is not None and rule.is_active else []
    if step >= len(plan):
        return "skipped: no such step"
    since = _aware(datetime.fromisoformat(started_at))
    now = datetime.now(UTC)
    reason = _stop_reason(db, tenant_id, rule, guest_id, conversation_id, since, now)
    adapter = None if reason else engine._adapter(db, tenant_id)
    if not reason and adapter is None:
        reason = "instagram_not_connected"
    if reason:
        engine.log_event(db, tenant_id, rule.id, "sequence_stopped", guest_id, detail=f"step {step + 1}: {reason}")
        db.commit()
        return f"stopped: {reason}"

    from app.models.guest import Guest
    from app.services import ig_automation_copy as copy_rules

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    item = plan[step]
    text, _changes = copy_rules.prepare_dm(
        engine._render(item.get("text") or "", guest), engine._keep_words(db, tenant_id)
    )
    button = item.get("button") or {}
    try:
        if button.get("url"):
            url = engine.tracked_url(db, tenant_id, rule.id, button["url"])
            try:
                result = adapter.send_link_button(recipient_id, text, button.get("title") or "Open", url)
            except Exception:  # noqa: BLE001 -- template refused: plain text + link still works
                text = f"{text}\n{url}"
                result = adapter.send_text(recipient_id, text)
        else:
            result = adapter.send_text(recipient_id, text)
    except Exception as exc:  # noqa: BLE001
        engine.log_event(db, tenant_id, rule.id, "dm_failed", guest_id, detail=f"follow-up {step + 1}: {exc}"[:300])
        db.commit()
        return "failed"
    engine._record(db, tenant_id, conversation_id, text, result, rule.id)
    engine.log_event(db, tenant_id, rule.id, "sequence_sent", guest_id, detail=f"step {step + 1}")
    db.commit()
    if step + 1 < len(plan):
        _queue(
            tenant_id,
            rule.id,
            guest_id,
            conversation_id,
            recipient_id,
            step + 1,
            started_at,
            plan[step + 1].get("after_minutes") or 60,
        )
    return "sent"
