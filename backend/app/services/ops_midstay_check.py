"""Mid-stay check (ops gap 9): one WhatsApp on day 2 of a 2+ night stay, so a problem the guest did not report surfaces
while it can still be fixed, not in a review.

Sending (from ops_auto_messages.run_tenant, hourly): the morning after check-in, 09:30-20:00 workspace time, files whose
booking is still live. One ops_auto_messages row (kind midstay_check, recipient guest); the message itself is keyed
"ops:{file}:midstay_check", so it goes once per stay ever. Text inside the guest's 24 h window
(wa_booking_messages.send_guest_text), else the approved haip_midstay_check_v1 template (wa_booking_pack). Anything
that holds it (template not approved with the window closed, STOP, AI off after the guest asked for a person, a person
already messaged them today, a personal-WhatsApp chat) = row status "skipped" + the reason, tried again next hour while
day 2 lasts. Never a Today need or a task.

Switch: ops_settings.midstay_check_enabled; NULL = on once the template is approved.

Reply (whatsapp.py, guest's first message within 24 h of the check): "1" / "all good" = positive on the stay file's
timeline and no AI reply; anything else = one ops item (category complaint, duty ops_manager, high) through
ops_escalation_service.create_item, and the AI still answers the guest.
"""

import re
from datetime import UTC, datetime, time, timedelta

import structlog
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.conversation import ChannelType, Conversation
from app.models.ops_files import OpsFile
from app.models.ops_fleet import OpsAutoMessage
from app.models.property import Property, Stay
from app.services import ops_auto_messages as auto
from app.services import ops_escalation_service as esc
from app.services import ops_money as money
from app.services import ops_pack_catalog as packs
from app.services import wa_booking_pack as pack

log = structlog.get_logger()

KIND = "midstay_check"
DAY_START, DAY_END = time(9, 30), time(20, 0)
MIN_NIGHTS = 2
LIVE_STAY = ("confirmed", "checked_in")
ENDED = (
    "returned",
    "checked_out",
    "settling",
    "closed",
    "cancelled",
)  # file states after the guest left (or never came)
ANSWER_WINDOW = timedelta(hours=24)
_POSITIVE = {
    "1",
    "all good",
    "all ok",
    "all okay",
    "all fine",
    "all well",
    "all is well",
    "good",
    "great",
    "fine",
    "ok",
    "okay",
    "yes",
    "perfect",
    "excellent",
    "everything good",
    "everything is good",
    "everything ok",
    "everything okay",
    "everything is fine",
    "everything fine",
    "👍",
    "👌",
}


def is_positive(text: str | None) -> bool:
    """The whole reply says all is well ("1", "All good", "ok thanks", "👍"); "1 but the AC is noisy" is not."""
    t = re.sub(r"[️\U0001F3FB-\U0001F3FF]", "", (text or "").lower())
    t = re.sub(r"[\s.!,]+", " ", t).strip()
    t = re.sub(r"\s*(thanks|thank you|thankyou|ty)$", "", t).strip()
    return t in _POSITIVE


def enabled(db: Session, tenant_id: str) -> bool:
    row = esc.get_settings_row(db, tenant_id)
    if row is not None and row.midstay_check_enabled is not None:
        return bool(row.midstay_check_enabled)
    return pack.statuses(db, tenant_id).get(pack.MIDSTAY_CHECK) == "approved"


def _phrase(f: OpsFile, unit_name: str | None) -> str:
    """'stay at Villa Amara' / 'trip in Ratha 1' (the pack's file + unit words)."""
    spec = packs.get(f.pack)
    prep = "in" if spec["unit_word"] == "vehicle" else "at"
    return f"{spec['file_word']} {prep} {unit_name or 'the ' + spec['unit_word']}"


def _open_conversation(db: Session, tenant_id: str, guest_id: str) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
        .order_by(Conversation.last_message_at.desc())
        .first()
    )


def _hold(db: Session, tenant_id: str, stay: Stay, now: datetime, tz) -> str | None:
    """Why the check may not go now, or None."""
    from app.services import ai_handoff
    from app.services import lead_playbook_guards as guards
    from app.services.sales_agent_service import guest_said_stop

    if stay.status not in LIVE_STAY:
        return "the booking is cancelled or checked out"
    guest = stay.guest
    if guest is None:
        return "no guest on the booking"
    problem = guards.phone_problem(db, tenant_id, guest)
    if problem:
        return problem
    if guest_said_stop(db, tenant_id, guest.id):
        return "the guest asked us to stop messaging them"
    conv = _open_conversation(db, tenant_id, guest.id)
    if conv is not None and conv.is_personal_bridge:
        return "the guest's chat is on personal WhatsApp"
    if conv is not None and ai_handoff.off_reason(db, tenant_id, conv):
        return "the guest asked for a person (AI is off on this chat)"
    midnight = datetime.combine(now.astimezone(tz).date(), time(0), tzinfo=tz).astimezone(UTC)
    if guards.contacted_since(db, tenant_id, guest.id, midnight):
        return "someone already messaged the guest today"
    return None


def _deliver(db: Session, f: OpsFile, stay: Stay, unit_name: str | None) -> tuple[str, str | None]:
    """(via, None) when queued, else (via, reason)."""
    from app.services.booking_agenda_service import whatsapp_state
    from app.services.guest_names import best_first_name
    from app.services.wa_booking_messages import Target, send_guest_template, send_guest_text

    first, phrase = best_first_name(db, f.tenant_id, stay.guest), _phrase(f, unit_name)
    target = Target("ops_file", f.id, "ops:", {"source": "ops", "ops_file_id": f.id}, "ops_file")
    common = {"target": target, "event": KIND, "sender_kind": "system", "autonomous": True}
    if whatsapp_state(db, f.tenant_id, stay.guest_id)["window_open"]:
        text = f"Hello {first}, everything okay with your {phrase}? Reply 1 if all good, or tell us what we can fix."
        out, via = send_guest_text(db, f.tenant_id, stay.guest, text, **common), "text"
    elif pack.statuses(db, f.tenant_id).get(pack.MIDSTAY_CHECK) == "approved":
        out, via = (
            send_guest_template(db, f.tenant_id, stay.guest, pack.MIDSTAY_CHECK, [first, phrase], **common),
            "template",
        )
    else:
        return "template", f"template {pack.MIDSTAY_CHECK} is not approved and the guest's 24-hour window is closed"
    return via, None if out["status"] in ("queued", "duplicate") else (out["reason"] or "not sent")


def _send(db: Session, f: OpsFile, stay: Stay, unit_name: str | None, now: datetime, tz) -> None:
    row = auto._row(db, f, KIND, "guest")
    if row is None:
        return
    via, reason = (None, why) if (why := _hold(db, f.tenant_id, stay, now, tz)) else _deliver(db, f, stay, unit_name)
    row.via, row.reason, row.attempts = via, reason, (row.attempts or 0) + 1
    row.status = "skipped" if reason else "sent"
    if row not in db:
        db.add(row)
    if reason:
        log.info("ops_midstay_check_skipped", tenant_id=f.tenant_id, file_id=f.id, reason=reason)
    else:
        row.sent_at = now
        money.event(
            db,
            f,
            f"Mid-stay check sent to the guest ({'WhatsApp message' if via == 'text' else 'template'}).",
            auto=True,
        )
    db.flush()


def run_tenant(db: Session, tenant_id: str, now: datetime, tz) -> None:
    """Day-2 checks due now. One commit per file (the guest senders commit too); a bad file is rolled back alone."""
    local = now.astimezone(tz)
    if not (DAY_START <= local.time() < DAY_END) or not enabled(db, tenant_id):
        return
    rows = (
        db.query(OpsFile, Stay, Property.name)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .outerjoin(Property, Property.id == Stay.property_id)
        .filter(
            OpsFile.tenant_id == tenant_id,
            Stay.tenant_id == tenant_id,
            Stay.check_in == local.date() - timedelta(days=1),
            OpsFile.state.notin_(ENDED),
        )
        .all()
    )
    for f, stay, unit_name in rows:
        if (stay.check_out - stay.check_in).days < MIN_NIGHTS:
            continue
        try:
            _send(db, f, stay, unit_name, now, tz)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.error("ops_midstay_check_failed", tenant_id=tenant_id, file_id=f.id, error=str(exc)[:300])


def on_guest_message(
    db: Session,
    tenant_id: str,
    guest_id: str | None,
    conversation_id: str | None,
    body: str | None,
    now: datetime | None = None,
) -> str | None:
    """The guest's answer to a check sent in the last 24 h: "positive" | "problem", or None when it is not one. Commits."""
    text = (body or "").strip()
    if not text or not guest_id:
        return None
    now = now or datetime.now(UTC)
    hit = (
        db.query(OpsAutoMessage, OpsFile, Stay)
        .join(OpsFile, OpsFile.id == OpsAutoMessage.file_id)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(
            OpsAutoMessage.tenant_id == tenant_id,
            OpsAutoMessage.kind == KIND,
            OpsAutoMessage.status == "sent",
            OpsAutoMessage.response.is_(None),
            Stay.tenant_id == tenant_id,
            Stay.guest_id == guest_id,
        )
        .order_by(OpsAutoMessage.sent_at.desc())
        .first()
    )
    if hit is None:
        return None
    row, f, stay = hit
    sent = row.sent_at if row.sent_at is None or row.sent_at.tzinfo else row.sent_at.replace(tzinfo=UTC)
    if sent is None or now - sent > ANSWER_WINDOW:
        return None
    answer = "positive" if is_positive(text) else "problem"
    claimed = db.execute(
        update(OpsAutoMessage)
        .where(OpsAutoMessage.id == row.id, OpsAutoMessage.response.is_(None))
        .values(response=answer)
        .execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:  # a second message raced this one: only the first answer counts
        return None
    sends: list[str] = []
    if answer == "positive":
        money.event(db, f, "Mid-stay check: the guest says all is good.", auto=True)
    else:
        unit = db.query(Property.name).filter_by(id=stay.property_id, tenant_id=tenant_id).scalar() or "Stay"
        _, sends = esc.create_item(
            db,
            tenant_id,
            title=f"{unit}: guest raised a problem mid-stay"[:200],
            severity="high",
            duty="ops_manager",
            kind="incident",
            category="complaint",
            source="guest_chat",
            summary=f"Reply to the mid-stay check: {text[:900]}",
            property_id=stay.property_id,
            stay_id=stay.id,
            guest_id=guest_id,
            conversation_id=conversation_id,
            now=now,
        )
        money.event(
            db, f, "Mid-stay check: the guest reported a problem. An ops item was raised for the manager.", auto=True
        )
    db.commit()
    if sends:
        from app.workers.tasks.ops_escalation import queue_delivery

        queue_delivery(tenant_id, sends)
    log.info("ops_midstay_check_answered", tenant_id=tenant_id, file_id=f.id, answer=answer)
    return answer
