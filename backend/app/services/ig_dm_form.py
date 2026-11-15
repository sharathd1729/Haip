"""Collect details inside an Instagram DM (Instagram Automations v2, phase 1).

After the person taps the automation's button (which opens Instagram's 24-hour window), HAIP asks the rule's
form.questions one at a time, with tap-to-answer chips; typed answers work too. The WhatsApp number is captured by the
same path every inbound DM goes through (chat_phone_capture -> identity_service.add_signal), so the person becomes a lead
the normal way, with consent and dedup. When the last answer arrives the answers are written onto the enquiry and the
rule's `message` (and button) is sent.

While a session is active and not expired the person's messages belong to the form: process_instagram_dm hands them here
before keyword rules and the AI concierge. "talk to a person" hands the chat to the team; "stop" ends it silently.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.models.ig_automation import IgFormSession
from app.services import ig_automation as engine

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=23)  # Instagram allows replies for 24 h after the person's last message; keep a margin
REMIND_AFTER_SECONDS = 3 * 3600  # one nudge if they go quiet mid-form (still inside the window)
FORM_PAYLOAD = "form"  # igauto:<rule>:form on answer chips; parse_payload ignores it, so the tap arrives as text
HUMAN_WORDS = ("talk to a person", "talk to someone", "speak to someone", "real person", "call me")
STOP_WORDS = ("stop", "unsubscribe", "cancel")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I)
NUMBER_RE = re.compile(r"\d+")
DEFAULT_RETRY = {
    "phone": "That number doesn't look right. Please send your WhatsApp number with the country code, like +91 98450 12345.",
    "email": "That email doesn't look right. Please send it again, like name@gmail.com.",
}
LABELS = {
    "dates": "Dates",
    "guests": "Guests",
    "phone": "Phone",
    "email": "Email",
    "budget": "Budget",
    "occasion": "Occasion",
}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite hands back naive datetimes


def questions(rule: AutomationRule) -> list[dict]:
    form = (rule.action_config or {}).get("form") or {}
    return list(form.get("questions") or []) if form.get("enabled") else []


def enabled(rule: AutomationRule) -> bool:
    return bool(questions(rule))


def active_session(db: Session, tenant_id: str, guest_id: str | None) -> IgFormSession | None:
    if not guest_id:
        return None
    return (
        db.query(IgFormSession)
        .filter(
            IgFormSession.tenant_id == tenant_id,
            IgFormSession.guest_id == guest_id,
            IgFormSession.status == "active",
            IgFormSession.expires_at > datetime.now(UTC),
        )
        .order_by(IgFormSession.created_at.desc())
        .first()
    )


def _chips(rule_id: str, options: list[str]) -> list[dict]:
    payload = engine._payload(rule_id, FORM_PAYLOAD)
    return [{"content_type": "text", "title": o[:20], "payload": payload} for o in options[:10]]


def _send(db, tenant_id, session, adapter, text: str, options: list[str] | None = None) -> bool:
    try:
        if options:
            result = adapter.send_quick_replies(session.recipient_id, text, _chips(session.rule_id, options))
        else:
            result = adapter.send_text(session.recipient_id, text)
    except Exception as exc:  # noqa: BLE001 -- logged; the form waits and the team sees the chat in the inbox
        logger.warning("ig_form_send_failed session=%s: %s", session.id, exc)
        engine.log_event(db, tenant_id, session.rule_id, "dm_failed", session.guest_id, detail=str(exc)[:300])
        return False
    engine._record(db, tenant_id, session.conversation_id, text, result, session.rule_id)
    return True


def _has_phone(db, tenant_id: str, guest_id: str) -> bool:
    from app.services import chat_phone_capture

    db.flush()  # sessions run with autoflush off: a number captured earlier in this same message must be visible
    return chat_phone_capture.guest_has_phone(db, tenant_id, guest_id)


def _next_step(db, tenant_id: str, rule: AutomationRule, session: IgFormSession, start: int) -> int:
    """The next question to ask from `start`: the phone question is skipped for someone HAIP already has a number for."""
    qs = questions(rule)
    i = start
    while i < len(qs) and qs[i].get("key") == "phone" and _has_phone(db, tenant_id, session.guest_id):
        session.answers = {**(session.answers or {}), "phone": "already on file"}
        i += 1
    return i


def _ask(db, tenant_id, rule, session, adapter, guest, *, prefix: str = "") -> None:
    q = questions(rule)[session.step]
    text = engine._render((prefix + q.get("text", "")).strip(), guest)
    if _send(db, tenant_id, session, adapter, text, q.get("options") or None):
        _schedule_reminder(session)


def _schedule_reminder(session: IgFormSession) -> None:
    try:
        from app.workers.tasks.ig_form_reminder import remind

        remind.apply_async(args=[session.tenant_id, session.id, session.step], countdown=REMIND_AFTER_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- a queue outage only loses the nudge
        logger.warning("ig_form_reminder_not_queued session=%s: %s", session.id, exc)


def start(
    db, tenant_id, rule, adapter, *, recipient_id: str, guest_id: str | None, conversation_id: str | None, guest=None
) -> bool:
    """Begin (or resume) the form for this person. True when it took over. Does not commit."""
    if not guest_id or not enabled(rule):
        return False
    current = active_session(db, tenant_id, guest_id)
    if current is not None and current.rule_id == rule.id:
        _ask(db, tenant_id, rule, current, adapter, guest)  # a second tap: ask the current question again
        return True
    if current is not None:
        current.status = "replaced"
    session = IgFormSession(
        tenant_id=tenant_id,
        rule_id=rule.id,
        guest_id=guest_id,
        conversation_id=conversation_id,
        recipient_id=recipient_id,
        step=0,
        answers={},
        status="active",
        expires_at=datetime.now(UTC) + WINDOW,
    )
    db.add(session)
    db.flush()
    engine.log_event(db, tenant_id, rule.id, "form_started", guest_id)
    session.step = _next_step(db, tenant_id, rule, session, 0)
    if session.step >= len(questions(rule)):
        _finish(db, tenant_id, rule, session, adapter, guest)
        return True
    _ask(db, tenant_id, rule, session, adapter, guest)
    return True


def start_from_trigger(db, tenant_id, rule, adapter, ctx: dict, recipient_id: str, guest, media_id) -> bool:
    """A DM keyword, story reply or ad chat: the chat is already open, so the questions start without a tap.
    True when the form took over (events, run log and commit done here, like engine.start's success path)."""
    guest_id, conversation_id = ctx.get("guest_id"), ctx.get("conversation_id")
    if not enabled(rule) or not start(
        db,
        tenant_id,
        rule,
        adapter,
        recipient_id=recipient_id,
        guest_id=guest_id,
        conversation_id=conversation_id,
        guest=guest,
    ):
        return False
    engine.log_event(db, tenant_id, rule.id, "dm_sent", guest_id, media_id)
    rule.run_count = (rule.run_count or 0) + 1
    rule.last_run_at = datetime.now(UTC)
    engine._log_run(db, tenant_id, rule, "success", "Started the questions", ctx)
    db.commit()
    return True


def _said(text: str, words) -> bool:
    t = f" {text.lower().strip()} "
    return any(f" {w} " in t or t.strip() == w for w in words)


def handle_inbound(db, tenant_id: str, guest_id: str | None, text: str | None, *, guest=None) -> bool:
    """A message from someone in the middle of a form. True when the form consumed it (nothing else should answer).
    Does not commit."""
    session = active_session(db, tenant_id, guest_id)
    if session is None or not text or text.startswith("["):
        return False
    rule = db.query(AutomationRule).filter_by(id=session.rule_id, tenant_id=tenant_id).first()
    qs = questions(rule) if rule is not None and rule.is_active else []
    if not qs or session.step >= len(qs):
        session.status = "stopped"
        return False
    session.expires_at = datetime.now(UTC) + WINDOW  # their message reopens Instagram's 24-hour window
    if text.strip().endswith("?"):
        return False  # a question, not an answer: the AI answers it and the form waits on the same question
    adapter = engine._adapter(db, tenant_id)
    if adapter is None:
        return False
    if _said(text, STOP_WORDS):
        session.status = "stopped"
        engine.log_event(db, tenant_id, rule.id, "form_dropped", guest_id, detail="stop")
        # one confirmation: it also keeps the reply safety net (reply_recovery) from waking the AI on this message
        _send(db, tenant_id, session, adapter, "Okay, I've stopped. Message us here anytime.")
        return True
    if _said(text, HUMAN_WORDS):
        session.status = "handed_over"
        engine.log_event(db, tenant_id, rule.id, "form_dropped", guest_id, detail="asked_for_a_person")
        _send(db, tenant_id, session, adapter, "Sure. Someone from our team will reply here shortly.")
        return True

    q = qs[session.step]
    key = q.get("key")
    answer, ok = _read(db, tenant_id, guest_id, key, text)
    if not ok:
        tries = int((session.answers or {}).get(f"_{key}_tries", 0)) + 1
        session.answers = {**(session.answers or {}), f"_{key}_tries": tries}
        if tries < 2:
            if _send(db, tenant_id, session, adapter, DEFAULT_RETRY.get(key, q.get("text", ""))):
                _schedule_reminder(session)
            return True
        if key == "phone":  # asked twice: let the team take it from here
            session.status = "handed_over"
            engine.log_event(db, tenant_id, rule.id, "form_dropped", guest_id, detail="no_valid_phone")
            _send(db, tenant_id, session, adapter, "Thanks! Someone from our team will reply here shortly.")
            return True
        answer = text.strip()[:200]  # an optional detail that didn't parse: keep what they wrote and move on
    label = "custom_" + str(session.step) if key == "custom" else key
    session.answers = {**(session.answers or {}), label: answer}
    session.step = _next_step(db, tenant_id, rule, session, session.step + 1)
    if session.step >= len(qs):
        _finish(db, tenant_id, rule, session, adapter, guest)
    else:
        _ask(db, tenant_id, rule, session, adapter, guest)
    return True


def _read(db, tenant_id: str, guest_id: str, key: str, text: str) -> tuple[str, bool]:
    """(answer to store, valid?) for one question type."""
    t = text.strip()
    if key == "phone":
        from app.services import chat_phone_capture

        # The DM task already ran chat_phone_capture on this message (that made the person a lead); the phone question is
        # only asked of someone with no number, so a number on file now came from this answer.
        if _has_phone(db, tenant_id, guest_id) or chat_phone_capture.capture_from_text(
            db, tenant_id, guest_id, t, source="instagram_form"
        ):
            return ("shared", True)  # the number itself lives on the guest (identity_service), never in the form row
        return ("", False)
    if key == "email":
        m = EMAIL_RE.search(t)
        return (m.group(0).lower(), True) if m else ("", False)
    return (t[:200], bool(t))


def _guests_count(answer: str | None) -> int | None:
    m = NUMBER_RE.search(answer or "")
    n = int(m.group(0)) if m else None
    return n if n and 0 < n <= 200 else None


def _finish(db, tenant_id, rule, session, adapter, guest) -> None:
    session.status = "completed"
    answers = session.answers or {}
    inquiry = _write_to_enquiry(db, tenant_id, session, rule, answers)
    agent = "our team"
    if inquiry is not None and inquiry.assigned_to:
        from app.models.user import User

        user = db.query(User).filter_by(id=inquiry.assigned_to, tenant_id=tenant_id).first()
        if user is not None and (user.name or "").strip():
            agent = user.name.split()[0]
    cfg = rule.action_config or {}
    text = engine._render(
        (cfg.get("message") or "Thanks! Our team will reply shortly.").replace("{agent_name}", agent), guest
    )
    button = cfg.get("button") or {}
    try:
        if button.get("url"):
            url = engine.tracked_url(db, tenant_id, rule.id, button["url"])
            try:
                result = adapter.send_link_button(session.recipient_id, text, button.get("title") or "Open", url)
            except Exception:  # noqa: BLE001 -- template refused: plain text + link still works
                text = f"{text}\n{url}"
                result = adapter.send_text(session.recipient_id, text)
        else:
            result = adapter.send_text(session.recipient_id, text)
        engine._record(db, tenant_id, session.conversation_id, text, result, rule.id)
    except Exception as exc:  # noqa: BLE001
        engine.log_event(db, tenant_id, rule.id, "dm_failed", session.guest_id, detail=str(exc)[:300])
    engine.log_event(db, tenant_id, rule.id, "form_completed", session.guest_id)
    if inquiry is not None:
        _refresh_summary(tenant_id, inquiry.id)
    from app.services import ig_suggest

    ig_suggest.after_final(db, tenant_id, rule, adapter, recipient_id=session.recipient_id, guest_id=session.guest_id,
                           conversation_id=session.conversation_id)


def _write_to_enquiry(db, tenant_id: str, session: IgFormSession, rule: AutomationRule, answers: dict):
    """Put the answers on the conversation's enquiry: guests as adults, occasion, and every answer as a readable note."""
    from app.models.conversation import Conversation
    from app.models.inquiry import Inquiry

    conv = (
        db.query(Conversation).filter_by(id=session.conversation_id, tenant_id=tenant_id).first()
        if session.conversation_id
        else None
    )
    if conv is None or not conv.inquiry_id:
        return None
    inquiry = db.query(Inquiry).filter_by(id=conv.inquiry_id, tenant_id=tenant_id).first()
    if inquiry is None:
        return None
    qs = questions(rule)
    lines = []
    for i, q in enumerate(qs):
        key = q.get("key")
        label = "custom_" + str(i) if key == "custom" else key
        value = answers.get(label)
        if not value or key == "phone":
            continue
        lines.append(f"{LABELS.get(key) or q.get('text', '')[:40]}: {value}")
    if not inquiry.adults:
        inquiry.adults = _guests_count(answers.get("guests"))
    if answers.get("occasion") and not inquiry.occasion:
        inquiry.occasion = str(answers["occasion"])[:100]
    if lines:
        note = "Instagram form: " + "; ".join(lines)
        inquiry.special_requests = f"{inquiry.special_requests}\n{note}" if inquiry.special_requests else note
    return inquiry


def _refresh_summary(tenant_id: str, inquiry_id: str) -> None:
    """The AI summary reads the dates out of the chat (generate_ai_summary); ask for a fresh one now."""
    try:
        from app.workers.tasks.generate_ai_summary import generate_ai_summary

        generate_ai_summary.delay(inquiry_id=inquiry_id, tenant_id=tenant_id, force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ig_form_summary_not_queued inquiry=%s: %s", inquiry_id, exc)


def remind(db, tenant_id: str, session_id: str, step: int) -> str:
    """The one nudge: only if the person is still on the same question and hasn't been nudged. Commits."""
    session = db.query(IgFormSession).filter_by(id=session_id, tenant_id=tenant_id).first()
    if (
        session is None
        or session.status != "active"
        or session.step != step
        or _aware(session.expires_at) <= datetime.now(UTC)
        or (session.answers or {}).get("_reminded")
    ):
        return "skipped"
    rule = db.query(AutomationRule).filter_by(id=session.rule_id, tenant_id=tenant_id).first()
    adapter = engine._adapter(db, tenant_id)
    if rule is None or adapter is None or step >= len(questions(rule)):
        return "skipped"
    session.answers = {**(session.answers or {}), "_reminded": True}
    from app.models.guest import Guest

    guest = db.query(Guest).filter_by(id=session.guest_id, tenant_id=tenant_id).first()
    q = questions(rule)[step]
    text = engine._render("Just checking in: " + q.get("text", ""), guest)
    sent = _send(db, tenant_id, session, adapter, text, q.get("options") or None)
    db.commit()
    return "sent" if sent else "failed"
