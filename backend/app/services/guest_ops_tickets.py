"""Guest ops tickets: a guest's in-stay problem and a booking's service request become ONE ops item (8 Nov 2026).

Before this, a guest's "AC not working" in chat went to ask-a-manager consults and a service request became a Task;
neither reached the on-duty person. Now both open an ``ops_items`` row through ``ops_escalation_service.create_item``,
so ``roster_service`` picks who hears it, with Acknowledge / Can't take it and timed escalation (no new store).

  open_for_chat          concierge_draft, when the guest has a LIVE stay and the turn is an in-stay problem
                         (``issue_category``: the extraction's ``stay_issue``, or the escalation keywords for safety /
                         legal / complaint, which the model cannot overrule). One ticket per (stay, category) while it is
                         live; the same message never opens two (``source_ref`` "msg:<id>", unique per tenant).
  send_ack               the honest line to the guest (autonomous mode only): who was alerted, never a time.
  link_service_request   a new StayServiceRequest opens its ticket ("ssr:<id>"); a future one is held until 09:00 local
                         on its due date (or check-in), like quiet hours. The request's Task mirror stays (My day).
  ask_confirmation       staff resolved it -> status "confirming" + "Is it fixed?" to the guest (in-window WhatsApp text
                         on the official number; never a personal-bridge thread). Not sendable = closed at once (logged).
  on_guest_message       the guest's YES closes it, NO reopens it and escalates one level.
  expire_confirmations   no answer within GUEST_CONFIRM_TIMEOUT (24 h) = closed (the escalation tick runs it).

Severity: safety (and any legal wording) = critical + every owner alerted at once; maintenance / complaint = high;
housekeeping / food = normal (held in quiet hours), raised to high when the guest is frustrated or urgent.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.conversation import Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.ops import OpsEscalationEvent, OpsItem
from app.models.ops_files import OpsFile
from app.models.property import Property, Stay
from app.services import ops_escalation_service as esc

log = structlog.get_logger()

CATEGORIES = ("maintenance", "housekeeping", "food", "safety", "complaint")
SEVERITY = {
    "safety": "critical",
    "maintenance": "high",
    "complaint": "high",
    "housekeeping": "normal",
    "food": "normal",
}
DUTY = {
    "maintenance": "maintenance",
    "housekeeping": "housekeeping",
    "food": "fnb",
    "safety": "ops_manager",
    "complaint": "ops_manager",
}
TITLE = {
    "maintenance": "a maintenance problem",
    "housekeeping": "a housekeeping problem",
    "food": "a food problem",
    "safety": "a safety issue",
    "complaint": "a complaint",
}
# escalation_policy categories that make a live-stay message a ticket even when the model said "none".
_ESCALATION_ISSUE = {
    "safety_medical": "safety",
    "legal": "complaint",
    "complaint": "complaint",
    "review_threat": "complaint",
}
LIVE = ("open", "acknowledged", "confirming")
STAY_LIVE_STATUSES = ("confirmed", "checked_in")
GUEST_CONFIRM_TIMEOUT = timedelta(hours=24)
ACK_KIND = "ai_holding"  # same kind as the consult's holding line: never a person's contact, never twice in a row
IDEM_PREFIX = "opi:"

_NO = re.compile(
    r"\b(no|nope|nah|not yet|not fixed|not working|still|nahi|nahin|nhi|broken|same problem|didn'?t)\b", re.IGNORECASE
)
_NOT_A_NO = re.compile(r"\bno (problem|problems|issue|issues|worries|complaints)\b", re.IGNORECASE)
_YES = re.compile(
    r"(\b(yes|yeah|yep|yup|ya|haan|han|ji|fixed|working|works|sorted|resolved|done|fine|all good|ok|okay|"
    r"thanks|thank you)\b|👍|✅)",
    re.IGNORECASE,
)


def _now(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now if now.tzinfo else now.replace(tzinfo=UTC)


def _audit(db: Session, item: OpsItem, action: str, actor: str, payload: dict | None = None) -> None:
    append_audit(
        db,
        tenant_id=item.tenant_id,
        action=action,
        target_type="ops_item",
        target_id=item.id,
        payload={"actor": actor, "source": item.source, "category": item.category, **(payload or {})},
    )


def _tenant_today(db: Session, tenant_id: str) -> date:
    from app.services.booking_agenda_service import tenant_today

    return tenant_today(db, tenant_id)


# ── Live stay + classification ────────────────────────────────────────────────


def live_stay(db: Session, tenant_id: str, guest_id: str | None, today: date | None = None) -> Stay | None:
    """The guest's stay happening now: confirmed / checked in, check-in today or earlier, check-out today or later, and
    not checked out on its ops file (the ops check-out does not change Stay.status). Newest check-in first."""
    if not guest_id:
        return None
    today = today or _tenant_today(db, tenant_id)
    returned = select(OpsFile.stay_id).where(OpsFile.tenant_id == tenant_id, OpsFile.returned_at.isnot(None))
    return (
        db.query(Stay)
        .filter(
            Stay.tenant_id == tenant_id,
            Stay.guest_id == guest_id,
            Stay.status.in_(STAY_LIVE_STATUSES),
            Stay.check_in <= today,
            Stay.check_out >= today,
            ~Stay.id.in_(returned),
        )
        .order_by(Stay.check_in.desc())
        .first()
    )


def issue_category(details: dict | None, escalation: dict | None) -> tuple[str | None, bool]:
    """(category, legal) for this turn, or (None, False) when it is not an in-stay problem. Safety and legal wording come
    from the escalation keywords (code), so the model cannot talk a safety message down to "none"."""
    cat = (details or {}).get("stay_issue")
    esc_cat = (escalation or {}).get("category")
    legal = esc_cat == "legal"
    if esc_cat == "safety_medical":
        return "safety", legal
    if cat in CATEGORIES:
        return cat, legal
    return _ESCALATION_ISSUE.get(esc_cat), legal


def guest_answer(text: str) -> str | None:
    """ "yes" / "no" to our "Is it fixed?", or None when the message is something else (left to the concierge)."""
    t = (text or "").strip()
    if not t or len(t.split()) > 12:
        return None
    if _NO.search(_NOT_A_NO.sub(" ", t)):
        return "no"
    return "yes" if _YES.search(t) else None


# ── Concierge: open or link a ticket ──────────────────────────────────────────


@dataclass
class TicketTurn:
    item_id: str
    created: bool
    held: bool  # first alert held (quiet hours): the guest is told so, never "alerted now"
    critical: bool


def _unit(db: Session, tenant_id: str, property_id: str | None) -> str:
    p = db.query(Property.name).filter_by(id=property_id, tenant_id=tenant_id).first() if property_id else None
    return (p[0] if p else None) or "Stay"


def _live_ticket(db: Session, tenant_id: str, stay_id: str, category: str) -> OpsItem | None:
    return (
        db.query(OpsItem)
        .filter(
            OpsItem.tenant_id == tenant_id,
            OpsItem.stay_id == stay_id,
            OpsItem.source == "guest_chat",
            OpsItem.category == category,
            OpsItem.status.in_(LIVE),
        )
        .order_by(OpsItem.created_at.desc())
        .first()
    )


def _turn(item: OpsItem, created: bool) -> TicketTurn:
    return TicketTurn(
        item_id=item.id,
        created=created,
        held=item.dispatched_step is None and item.dispatch_after is not None,
        critical=item.severity == "critical",
    )


def open_for_chat(
    db: Session,
    tenant,
    conversation: Conversation,
    guest_id: str | None,
    *,
    message_id: str,
    burst_text: str,
    details: dict | None,
    escalation: dict | None,
    now: datetime | None = None,
) -> TicketTurn | None:
    """Open (or link to) the guest's ticket for this turn. Commits and queues the alerts. None = not an in-stay problem,
    no live stay, or a failure (logged: the consult path then runs as before)."""
    category, legal = issue_category(details, escalation)
    if category is None:
        return None
    try:
        stay = live_stay(db, tenant.id, guest_id)
        if stay is None:
            return None
        ref = f"msg:{message_id}"
        same = db.query(OpsItem).filter_by(tenant_id=tenant.id, source_ref=ref).first()
        if same is not None:
            return _turn(same, False)
        existing = _live_ticket(db, tenant.id, stay.id, category)
        if existing is not None:
            seen = (
                db.query(OpsEscalationEvent.detail)
                .filter_by(tenant_id=tenant.id, item_id=existing.id, event="guest_message")
                .all()
            )
            if not any((d or {}).get("message_id") == message_id for (d,) in seen):
                esc._event(
                    db,
                    existing,
                    "guest_message",
                    _now(now),
                    detail={"message_id": message_id, "text": (burst_text or "")[:500]},
                )
                db.commit()
            return _turn(existing, False)

        severity = "critical" if legal else SEVERITY[category]
        if severity == "normal" and (
            (details or {}).get("sentiment") == "frustrated" or (details or {}).get("urgency") == "high"
        ):
            severity = "high"
        try:
            with db.begin_nested():
                item, send_ids = esc.create_item(
                    db,
                    tenant.id,
                    title=f"{_unit(db, tenant.id, stay.property_id)}: Guest reports {TITLE[category]}",
                    summary=(burst_text or "").strip()[:500] or None,
                    kind="incident",
                    category=category,
                    severity=severity,
                    duty=DUTY[category],
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    guest_id=stay.guest_id,
                    conversation_id=conversation.id,
                    source="guest_chat",
                    source_ref=ref,
                    now=now,
                )
                if severity == "critical":
                    send_ids += esc.notify_owners_now(db, item, now)
                _audit(
                    db,
                    item,
                    "ops.item.guest_ticket_opened",
                    "concierge",
                    {"severity": severity, "legal": legal, "message_id": message_id},
                )
        except IntegrityError:  # the same message raced in: use that ticket
            same = db.query(OpsItem).filter_by(tenant_id=tenant.id, source_ref=ref).first()
            return _turn(same, False) if same is not None else None
        db.commit()
        from app.workers.tasks.ops_escalation import queue_delivery

        queue_delivery(tenant.id, send_ids)
        log.info(
            "guest_ticket_opened",
            tenant_id=tenant.id,
            item_id=item.id,
            category=category,
            severity=severity,
            held=bool(item.dispatch_after and item.dispatched_step is None),
        )
        return _turn(item, True)
    except Exception as exc:  # noqa: BLE001 -- the reply path must not fail on this
        db.rollback()
        log.error("guest_ticket_open_failed", conversation_id=conversation.id, error=str(exc)[:300])
        return None


def ack_text(turn: TicketTurn) -> str:
    """What the guest is told. Honest about who knows; never a time no staff member confirmed."""
    if turn.critical:
        return (
            "I'm so sorry. I've alerted our team and the owner right now. If anyone is hurt or in danger, please call "
            "112 straight away."
        )
    if not turn.created:
        return "Thank you, I've added this to the issue our on-site team already has open."
    if turn.held:
        return (
            "Sorry about this. I've logged it for our on-site team; they are off for the night and will see it as soon "
            "as they start in the morning."
        )
    return "Sorry about this. I've passed it to our on-site team and alerted them now. They will update you here."


def send_ack(
    db: Session, tenant, conversation: Conversation, turn: TicketTurn, *, message_id: str, ai_mode: str
) -> Message | None:
    """The honest line, where the AI would otherwise answer on its own. Same rules as the consult's holding reply:
    WhatsApp / Instagram, inside the 24 h window, never a personal-bridge thread, never twice in a row. Commits."""
    from app.services import agent_consult_service as consults
    from app.services.agent_consult_flow import _channel, _last_outbound

    try:
        channel = _channel(conversation)
        if ai_mode != "autonomous" or conversation.is_personal_bridge or channel not in ("whatsapp", "instagram"):
            return None
        if not consults.window_open(db, tenant.id, conversation.id):
            return None
        last = _last_outbound(db, tenant.id, conversation.id)
        if last is not None and last.sender_kind == ACK_KIND:
            return None
        msg = Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            direction=MessageDirection.OUTBOUND,
            channel=conversation.channel,
            body=ack_text(turn),
            is_ai_generated=False,
            sent_autonomously=True,
            sender_kind=ACK_KIND,
            sender_name="AI Concierge",
            was_approved=True,
            delivery_state=MessageDeliveryState.QUEUED,
            channel_status="queued",
            idempotency_key=f"ops-ack:{turn.item_id}:{message_id}"[:64],
            channel_metadata={"source": "guest_ops_ticket", "ops_item_id": turn.item_id, "holding": True},
        )
        db.add(msg)
        conversation.last_message_at = datetime.now(UTC).isoformat()
        db.commit()
        consults.queue_send(msg.id, tenant.id, channel)
        return msg
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.error("guest_ticket_ack_failed", conversation_id=conversation.id, error=str(exc)[:200])
        return None


# ── Service requests ──────────────────────────────────────────────────────────


def _morning(db: Session, tenant_id: str, day: date) -> datetime:
    from app.services import roster_service

    return datetime.combine(day, time(9, 0), tzinfo=roster_service.tenant_tz(db, tenant_id)).astimezone(UTC)


def link_service_request(
    db: Session, tenant_id: str, stay: Stay, req, *, created_by: str | None = None, now: datetime | None = None
) -> list[str]:
    """Open the request's ticket (or return [] when it already has one, or the booking is over / cancelled). Caller
    commits, then queues the returned send ids."""
    if db.query(OpsItem.id).filter_by(tenant_id=tenant_id, source_ref=f"ssr:{req.id}").first() is not None:
        return []
    today = _tenant_today(db, tenant_id)
    if stay.status not in STAY_LIVE_STATUSES or stay.check_out < today:
        return []
    day = req.due_date or stay.check_in
    item, send_ids = esc.create_item(
        db,
        tenant_id,
        title=f"{_unit(db, tenant_id, stay.property_id)}: {req.title}"[:200],
        summary=req.notes or None,
        kind="incident",
        category="service_request",
        severity="normal",
        duty="front_desk",
        property_id=stay.property_id,
        stay_id=stay.id,
        guest_id=stay.guest_id,
        service_request_id=req.id,
        source="service_request",
        source_ref=f"ssr:{req.id}",
        created_by=created_by,
        dispatch_after=_morning(db, tenant_id, day) if day > today else None,
        now=now,
    )
    _audit(db, item, "ops.item.guest_ticket_opened", "staff", {"service_request_id": req.id, "by": created_by})
    return send_ids


def ticket_for_request(db: Session, tenant_id: str, request_id: str) -> OpsItem | None:
    return (
        db.query(OpsItem)
        .filter_by(tenant_id=tenant_id, service_request_id=request_id)
        .order_by(OpsItem.created_at.desc())
        .first()
    )


def request_changed(
    db: Session, tenant_id: str, req, *, status_changed: bool, due_changed: bool, stay: Stay, user_id: str | None
) -> tuple[list[str], OpsItem | None]:
    """Keep the ticket in step with an edited request: done = resolved (the caller then asks the guest, after commit),
    reopened while waiting for the guest = reopened, a new due date moves a not-yet-sent alert.
    Returns (send ids to queue after commit, the ticket to ask_confirmation on)."""
    item = ticket_for_request(db, tenant_id, req.id)
    if item is None:
        return [], None
    if status_changed and req.status == "done" and item.status in ("open", "acknowledged"):
        esc.resolve(db, item, user_id=user_id, note="Service request marked done")
        _audit(db, item, "ops.item.resolved", "staff", {"by": user_id})
        return [], item if item.status == "confirming" else None
    if status_changed and req.status == "open" and item.status == "confirming":
        return _reopen(db, item, "staff_reopened", sync_request=False), None
    if due_changed and item.status == "open" and item.dispatched_step is None:
        day = req.due_date or stay.check_in
        item.dispatch_after = _morning(db, tenant_id, day) if day > _tenant_today(db, tenant_id) else _now()
    return [], None


def request_removed(db: Session, tenant_id: str, request_id: str, user_id: str) -> None:
    item = ticket_for_request(db, tenant_id, request_id)
    if item is not None and esc.cancel(db, item, user_id=user_id, note="Service request removed"):
        _audit(db, item, "ops.item.cancelled", "staff", {"by": user_id})


def _sync_request(db: Session, item: OpsItem, done: bool) -> None:
    if not item.service_request_id:
        return
    from app.models.stay_finance import StayServiceRequest
    from app.models.task import Task

    req = db.query(StayServiceRequest).filter_by(id=item.service_request_id, tenant_id=item.tenant_id).first()
    if req is None or (req.status == "done") == done:
        return
    req.status = "done" if done else "open"
    req.completed_at = _now() if done else None
    task = db.query(Task).filter_by(id=req.task_id, tenant_id=item.tenant_id).first() if req.task_id else None
    if task is not None:
        task.is_done, task.completed_at = done, req.completed_at


# ── Close only on the guest's word ────────────────────────────────────────────


def _close(db: Session, item: OpsItem, reason: str, actor: str, now: datetime | None = None) -> None:
    now = _now(now)
    item.status = "resolved"
    esc._event(db, item, "guest_confirmed" if reason == "guest_yes" else "closed", now, detail={"reason": reason})
    _sync_request(db, item, True)
    _audit(
        db, item, "ops.item.guest_confirmed" if reason == "guest_yes" else "ops.item.closed", actor, {"reason": reason}
    )
    db.flush()


def _reopen(
    db: Session, item: OpsItem, reason: str, *, sync_request: bool = True, now: datetime | None = None
) -> list[str]:
    """Back to open and one level up the chain (the guest says it is not fixed)."""
    now = _now(now)
    item.status = "open"
    item.resolved_at = item.resolved_by_staff_id = item.resolved_by_user_id = None
    item.acknowledged_at = item.acknowledged_by_staff_id = item.acknowledged_by_user_id = None
    item.resolve_breached_at = None
    item.escalation_exhausted = False
    esc._event(db, item, "reopened", now, detail={"reason": reason})
    if sync_request:
        _sync_request(db, item, False)
    _audit(
        db,
        item,
        "ops.item.guest_reopened" if reason == "guest_no" else "ops.item.reopened",
        "guest" if reason == "guest_no" else "staff",
        {"reason": reason},
    )
    db.flush()
    return esc.escalate(db, item, now)


def ask_confirmation(db: Session, item: OpsItem, now: datetime | None = None) -> str:
    """After staff resolve a guest ticket: "Is it fixed?" to the guest. Returns "asked", or "closed" when it cannot be
    asked (window closed, no WhatsApp, personal-bridge only). Commits."""
    from app.models.guest import Guest
    from app.services import wa_booking_messages as wa

    if item.status != "confirming":
        return item.status
    guest = db.query(Guest).filter_by(id=item.guest_id, tenant_id=item.tenant_id).first()
    asked = (
        db.query(OpsEscalationEvent.id)
        .filter_by(tenant_id=item.tenant_id, item_id=item.id, event="confirm_asked")
        .count()
    )
    label = (
        f'your request "{item.title.split(": ", 1)[-1]}"'
        if item.source == "service_request"
        else f"the {(item.category or 'problem').replace('_', ' ')} issue you reported"
    )
    text = f"Our team says {label} is sorted. Is everything fine now? Please reply YES or NO."
    target = wa.Target("ops_item", item.id, IDEM_PREFIX, {"source": "ops_item", "ops_item_id": item.id}, "ops_item")
    res = (
        wa.send_guest_text(
            db,
            item.tenant_id,
            guest,
            text,
            target=target,
            event=f"confirm{asked + 1}",
            sender_kind="system",
            autonomous=True,
        )
        if guest is not None
        else {"status": "skipped", "reason": "guest not found"}
    )
    if res["status"] in ("queued", "duplicate"):
        esc._event(db, item, "confirm_asked", _now(now), detail={"message_id": res.get("message_id")})
        _audit(db, item, "ops.item.confirmation_asked", "system", {"message_id": res.get("message_id")})
        db.commit()
        return "asked"
    _close(db, item, f"not asked: {res.get('reason')}", "system", now)
    db.commit()
    return "closed"


def on_guest_message(
    db: Session, tenant_id: str, guest_id: str | None, body: str, now: datetime | None = None
) -> str | None:
    """A guest's WhatsApp message while one of their tickets waits for an answer: "confirmed", "reopened" or None
    (not a clear yes / no, or nothing waiting). Commits and queues the escalation alerts. Never raises."""
    if not guest_id or not (body or "").strip():
        return None
    now = _now(now)
    try:
        item = (
            db.query(OpsItem)
            .filter(
                OpsItem.tenant_id == tenant_id,
                OpsItem.guest_id == guest_id,
                OpsItem.status == "confirming",
                OpsItem.resolved_at >= now - GUEST_CONFIRM_TIMEOUT,
            )
            .order_by(OpsItem.resolved_at.desc())
            .first()
        )
        if item is None:
            return None
        answer = guest_answer(body)
        if answer is None:
            return None
        if answer == "yes":
            _close(db, item, "guest_yes", "guest", now)
            db.commit()
            return "confirmed"
        send_ids = _reopen(db, item, "guest_no", now=now)
        db.commit()
        from app.workers.tasks.ops_escalation import queue_delivery

        queue_delivery(tenant_id, send_ids)
        return "reopened"
    except Exception as exc:  # noqa: BLE001 -- the message is stored either way
        db.rollback()
        log.error("guest_ticket_answer_failed", tenant_id=tenant_id, error=str(exc)[:200])
        return None


def expire_confirmations(db: Session, tenant_id: str, now: datetime | None = None, limit: int = 200) -> int:
    """Close guest tickets whose "Is it fixed?" got no answer within GUEST_CONFIRM_TIMEOUT. Caller commits."""
    now = _now(now)
    rows = (
        db.query(OpsItem)
        .filter(
            OpsItem.tenant_id == tenant_id,
            OpsItem.status == "confirming",
            or_(OpsItem.resolved_at.is_(None), OpsItem.resolved_at < now - GUEST_CONFIRM_TIMEOUT),
        )
        .limit(limit)
        .all()
    )
    for item in rows:
        _close(db, item, "no_reply_timeout", "system", now)
    return len(rows)
