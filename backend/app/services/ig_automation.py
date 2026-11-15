"""Instagram automations: comment / Live / story / DM keyword → DM, with an optional follow gate and a tracked link button.

Rules are automation_rules rows (action send_instagram_quick_reply, config in schemas/ig_automation.py); matching stays in
ig_keyword_match. This module runs a matched rule for one person:

1. start(): public reply to a comment (random from public_ack_pool), then the DM. A comment can only be answered with
   Meta's one *private reply* (within 7 days); a plain DM to someone who only commented is refused. When the rule has a
   button or a follow gate, the first DM is the opener with a quick-reply "Send it" (payload igauto:<rule>:open): the tap
   opens the normal 24h window, which the link button and the follow check need.
2. handle_payload(): the tap. Follow gate: Meta's is_user_follow_business; not following -> ask (quick reply
   igauto:<rule>:followed) up to max_asks, then send anyway or stop. Meta answers only once the person has messaged us;
   when it will not say, the "I'm following" tap is taken at its word.
3. The final message: text + one link button (generic template), the link a tracked /l/ redirect; plain text + link when
   Meta refuses the template.

Every send writes an outbound Message (sender_kind "automation", never counted as a person's contact) and an
ig_automation_events row; the events drive once-per-person, the hourly caps and the stats.
"""

from __future__ import annotations

import logging
import random
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.automation import AutomationRule, AutomationRun
from app.models.ig_automation import IgAutomationEvent, IgTrackedLink

logger = logging.getLogger(__name__)

PAYLOAD_PREFIX = "igauto:"
SENT_KINDS = ("dm_sent", "link_sent", "gate_asked")
TENANT_HOURLY_CAP = 200  # automated sends per workspace per hour (Meta rate limits)
GUEST_HOURLY_CAP = 5  # automated sends per person per hour
DEFAULT_ACK = "Check your DMs! 📥"
ALREADY_REPLIED = "2534023"  # Meta error_subcode: "The comment you are trying to reply to already has a reply"


# ── small helpers ────────────────────────────────────────────────────────────────────────────────────────────────────


def log_event(
    db: Session,
    tenant_id: str,
    rule_id: str,
    kind: str,
    guest_id: str | None = None,
    media_id: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        IgAutomationEvent(
            tenant_id=tenant_id,
            rule_id=rule_id,
            kind=kind,
            guest_id=guest_id,
            media_id=(media_id or None) and media_id[:64],
            detail=(detail or None) and detail[:300],
        )
    )


def _log_run(db: Session, tenant_id: str, rule: AutomationRule, status: str, detail: str, context: dict) -> None:
    db.add(
        AutomationRun(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            automation_id=rule.id,
            automation_name=rule.name,
            status=status,
            trigger_event=rule.trigger,
            context=context,
            detail=detail[:500],
        )
    )


def _adapter(db: Session, tenant_id: str):
    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    from app.core.encryption import decrypt_credentials
    from app.models.integration import INSTAGRAM_INBOUND_STATUSES, Integration

    integ = (
        db.query(Integration)
        .filter(
            Integration.tenant_id == tenant_id,
            Integration.kind == "instagram",
            Integration.status.in_(INSTAGRAM_INBOUND_STATUSES),
        )
        .first()
    )
    if not integ or not integ.credentials_kms_blob:
        return None
    creds = decrypt_credentials(integ.credentials_kms_blob)
    token = creds.get("access_token", "")
    account = (integ.config or {}).get("instagram_business_account_id", "")
    return InstagramGraphAdapter(access_token=token, ig_account_id=account) if token and account else None


def _keep_words(db: Session, tenant_id: str):
    """Words the humanizer must leave alone for this workspace (Instagram toolkit phase 5)."""
    from app.models.tenant import Tenant
    from app.services.marketing_humanize import keep_words

    return keep_words(db.query(Tenant).filter_by(id=tenant_id).first())


def _render(text: str, guest) -> str:
    name = (getattr(guest, "name", "") or "").strip().lstrip("@")
    first = name.split()[0] if name and not name.startswith("IG User") else "there"
    return (text or "").replace("{first_name}", first)


def _count(
    db: Session,
    tenant_id: str,
    *,
    rule_id: str | None = None,
    guest_id: str | None = None,
    kinds=SENT_KINDS,
    since: datetime | None = None,
) -> int:
    q = db.query(IgAutomationEvent).filter(IgAutomationEvent.tenant_id == tenant_id, IgAutomationEvent.kind.in_(kinds))
    if rule_id:
        q = q.filter(IgAutomationEvent.rule_id == rule_id)
    if guest_id:
        q = q.filter(IgAutomationEvent.guest_id == guest_id)
    if since:
        q = q.filter(IgAutomationEvent.created_at >= since)
    return q.count()


def skip_reason(
    db: Session, tenant_id: str, rule: AutomationRule, guest_id: str | None, *, starting: bool
) -> str | None:
    """Why this rule must not message this person now, or None."""
    from app.services.sales_agent_service import guest_said_stop

    if guest_said_stop(db, tenant_id, guest_id):
        return "guest_said_stop"
    hour = datetime.now(UTC) - timedelta(hours=1)
    if _count(db, tenant_id, since=hour) >= TENANT_HOURLY_CAP:
        return "workspace_hourly_cap"
    if guest_id and _count(db, tenant_id, guest_id=guest_id, since=hour) >= GUEST_HOURLY_CAP:
        return "person_hourly_cap"
    if (
        starting
        and (rule.action_config or {}).get("once_per_person", True)
        and guest_id
        and _count(db, tenant_id, rule_id=rule.id, guest_id=guest_id, kinds=("dm_sent", "link_sent"))
    ):
        return "already_sent_to_this_person"
    return None


def _record(db: Session, tenant_id: str, conversation_id: str | None, text: str, result: dict, rule_id: str) -> None:
    """The DM as an outbound Message so it shows in the Inbox thread (the echo webhook dedups on the same mid)."""
    if not conversation_id:
        return
    from app.models.conversation import ChannelType, Message, MessageDeliveryState, MessageDirection

    mid = (result or {}).get("message_id")
    db.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction=MessageDirection.OUTBOUND,
            channel=ChannelType.INSTAGRAM,
            body=text,
            channel_message_id=mid,
            channel_status="sent",
            delivery_state=MessageDeliveryState.SENT,
            sender_kind="automation",
            channel_metadata={"automation_rule_id": rule_id},
        )
    )


def tracked_url(db: Session, tenant_id: str, rule_id: str, target_url: str) -> str:
    """A short /l/<slug>/<code> link that logs a click and redirects to target_url (one code per rule + target)."""
    from app.core.config import settings
    from app.models.tenant import Tenant

    row = db.query(IgTrackedLink).filter_by(tenant_id=tenant_id, rule_id=rule_id, target_url=target_url).first()
    if row is None:
        row = IgTrackedLink(
            tenant_id=tenant_id, rule_id=rule_id, target_url=target_url, code=secrets.token_urlsafe(8)[:10]
        )
        db.add(row)
        db.flush()
    slug = db.query(Tenant.slug).filter(Tenant.id == tenant_id).scalar()
    base = (settings.API_BASE_URL or "").rstrip("/")
    return f"{base}/api/v1/l/{slug}/{row.code}" if base and slug else target_url


def _payload(rule_id: str, step: str) -> str:
    return f"{PAYLOAD_PREFIX}{rule_id}:{step}"


def _quick(title: str, rule_id: str, step: str) -> list[dict]:
    return [{"content_type": "text", "title": (title or "Send it")[:20], "payload": _payload(rule_id, step)}]


# ── the steps ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _final_text(db: Session, tenant_id: str, rule: AutomationRule, guest, keep) -> str:
    """The final message as plain text: the rule's message, then its link (tracked) when it has a button."""
    from app.services import ig_automation_copy as copy_rules

    cfg = rule.action_config or {}
    text, _changes = copy_rules.prepare_dm(_render(cfg.get("message") or "", guest), keep)
    url = (cfg.get("button") or {}).get("url")
    return f"{text}\n{tracked_url(db, tenant_id, rule.id, url)}" if url else text


def start(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    *,
    recipient_id: str,
    guest_id: str | None,
    conversation_id: str | None,
    comment_id: str | None = None,
    media_id: str | None = None,
    guest=None,
) -> bool:
    """Run a matched rule for one person. True when the DM went out. Commits."""
    cfg = rule.action_config or {}
    ctx = {"conversation_id": conversation_id, "guest_id": guest_id, "comment_id": comment_id, "media_id": media_id}
    log_event(db, tenant_id, rule.id, "triggered", guest_id, media_id)
    reason = skip_reason(db, tenant_id, rule, guest_id, starting=True)
    if not cfg.get("message"):
        reason = reason or "no_message"
    # One answer per comment. Meta can deliver the same comment twice at once (both copies pass the ingest dedup before
    # either commits); the second private reply then fails with "already has a reply" (subcode 2534023, seen live).
    if not reason and comment_id:
        from app.core import cache

        if not cache.idem_check_and_set(f"igauto:comment:{tenant_id}:{comment_id}", ttl=8 * 86400):
            reason = "comment_already_answered"
    adapter = None if reason else _adapter(db, tenant_id)
    if not reason and adapter is None:
        reason = "instagram_not_connected"
    if reason:
        log_event(db, tenant_id, rule.id, "skipped", guest_id, media_id, reason)
        _log_run(db, tenant_id, rule, "skipped", reason, ctx)
        db.commit()
        return False

    from app.services import ig_automation_copy as copy_rules

    keep = _keep_words(db, tenant_id)
    notes: list[str] = []

    if comment_id:
        ack = random.choice(cfg.get("public_ack_pool") or [DEFAULT_ACK])
        ack, _changes, replaced = copy_rules.prepare_public(ack, keep)
        if replaced:
            notes.append(f"public reply replaced: {replaced}")
        try:
            adapter.reply_to_comment(comment_id, ack)
            log_event(db, tenant_id, rule.id, "public_reply", guest_id, media_id)
        except Exception as exc:  # noqa: BLE001 -- best effort; the DM is what answers the person
            logger.warning("ig_automation_public_reply_failed rule=%s: %s", rule.id, exc)

    gate = cfg.get("follow_gate") or {}
    from app.services import ig_dm_form  # DM forms (Automations v2): an open chat starts the questions at once

    if (
        not comment_id
        and not gate.get("enabled")
        and ig_dm_form.start_from_trigger(db, tenant_id, rule, adapter, ctx, recipient_id, guest, media_id)
    ):
        return True
    needs_tap = bool(cfg.get("button") or gate.get("enabled") or ig_dm_form.enabled(rule))
    text, _changes = copy_rules.prepare_dm(_render(cfg.get("opener") if needs_tap else cfg["message"], guest), keep)
    quick = _quick(cfg.get("opener_button"), rule.id, "open") if needs_tap else None
    delivered_final = False
    try:
        if comment_id:
            try:
                result = adapter.send_private_reply(comment_id, text, quick)
            except Exception as exc:  # noqa: BLE001
                if not quick or ALREADY_REPLIED in str(exc):
                    raise
                # Meta refused the first reply with a tap button (seen live as a 500). The comment's one private reply
                # is still unused, so send the whole message instead: text + link, no button, no follow check.
                logger.warning("ig_automation_private_reply_button_refused rule=%s: %s", rule.id, exc)
                text = _final_text(db, tenant_id, rule, guest, keep)
                result = adapter.send_private_reply(comment_id, text, None)
                delivered_final = True
                notes.append("sent as plain text: Instagram refused the button")
        elif quick:
            result = adapter.send_quick_replies(recipient_id, text, quick)
        else:
            result = adapter.send_text(recipient_id, text)
    except Exception as exc:  # noqa: BLE001
        if comment_id and ALREADY_REPLIED in str(exc):
            # Someone (or an earlier copy of this event) already answered the comment privately: nothing went wrong.
            log_event(db, tenant_id, rule.id, "skipped", guest_id, media_id, "comment_already_answered")
            _log_run(db, tenant_id, rule, "skipped", "This comment already has a private reply", ctx)
            db.commit()
            return False
        logger.error("ig_automation_dm_failed rule=%s: %s", rule.id, exc)
        log_event(db, tenant_id, rule.id, "dm_failed", guest_id, media_id, str(exc)[:500])
        _log_run(db, tenant_id, rule, "failed", f"Send failed: {str(exc)[:500]}", ctx)
        db.commit()
        return False

    _record(db, tenant_id, conversation_id, text, result, rule.id)
    log_event(db, tenant_id, rule.id, "dm_sent", guest_id, media_id)
    if delivered_final:
        log_event(db, tenant_id, rule.id, "link_sent", guest_id, media_id)
    rule.run_count = (rule.run_count or 0) + 1
    rule.last_run_at = datetime.now(UTC)
    if not comment_id and rule.trigger == "ig_dm_received" and (cfg.get("follow_up") or "").strip():
        from app.services.ig_quick_reply import _queue_follow_up

        notes.append(
            _queue_follow_up(tenant_id, rule, recipient_id, guest_id, conversation_id, copy_rules.follow_up_hours(cfg))
        )
    _log_run(db, tenant_id, rule, "success", f"Sent: {text[:100]}" + (f" ({'; '.join(notes)})" if notes else ""), ctx)
    db.commit()
    if not comment_id and not needs_tap:  # the final message went out in an open chat: follow-ups may follow
        from app.services import ig_sequence

        ig_sequence.begin(rule, tenant_id, recipient_id=recipient_id, guest_id=guest_id, conversation_id=conversation_id)
    return True


def parse_payload(payload: str | None) -> tuple[str, str] | None:
    """(rule_id, step) from an igauto:<rule>:<step> quick-reply / postback payload, else None."""
    if not payload or not payload.startswith(PAYLOAD_PREFIX):
        return None
    parts = payload[len(PAYLOAD_PREFIX) :].split(":")
    return (parts[0], parts[1]) if len(parts) == 2 and parts[1] in ("open", "followed") else None


def handle_payload(
    db: Session,
    tenant_id: str,
    payload: str,
    *,
    recipient_id: str,
    guest_id: str | None,
    conversation_id: str | None,
    guest=None,
) -> bool:
    """A tap on one of our buttons. True when it was ours (handled, even if nothing was sent). Commits."""
    parsed = parse_payload(payload)
    if not parsed:
        return False
    rule_id, step = parsed
    rule = db.query(AutomationRule).filter_by(id=rule_id, tenant_id=tenant_id, is_active=True).first()
    if rule is None:
        return True
    cfg = rule.action_config or {}
    ctx = {"conversation_id": conversation_id, "guest_id": guest_id, "step": step}
    if guest_id and _count(db, tenant_id, rule_id=rule.id, guest_id=guest_id, kinds=("link_sent", "form_completed")):
        return True  # already has the link; a second tap sends nothing
    reason = skip_reason(db, tenant_id, rule, guest_id, starting=False)
    adapter = None if reason else _adapter(db, tenant_id)
    if not reason and adapter is None:
        reason = "instagram_not_connected"
    if reason:
        log_event(db, tenant_id, rule.id, "skipped", guest_id, detail=reason)
        db.commit()
        return True

    gate = cfg.get("follow_gate") or {}
    if gate.get("enabled"):
        follows = adapter.follows_us(recipient_id)
        trusted_tap = follows is None and step == "followed"  # Meta would not say: take the tap at its word
        if follows or trusted_tap:
            log_event(db, tenant_id, rule.id, "followed", guest_id, detail="checked" if follows else "self_confirmed")
        else:
            asked = _count(db, tenant_id, rule_id=rule.id, guest_id=guest_id, kinds=("gate_asked",)) if guest_id else 0
            if asked < int(gate.get("max_asks") or 3):
                text = _render(gate.get("ask_text") or "Please follow us first, then tap below 👇", guest)
                try:
                    result = adapter.send_quick_replies(
                        recipient_id, text, _quick(gate.get("button_title") or "I'm following", rule.id, "followed")
                    )
                except Exception as exc:  # noqa: BLE001
                    log_event(db, tenant_id, rule.id, "dm_failed", guest_id, detail=str(exc))
                    db.commit()
                    return True
                _record(db, tenant_id, conversation_id, text, result, rule.id)
                log_event(db, tenant_id, rule.id, "gate_asked", guest_id)
                db.commit()
                return True
            if not gate.get("send_anyway", True):
                log_event(db, tenant_id, rule.id, "skipped", guest_id, detail="not_following")
                db.commit()
                return True

    from app.services import ig_dm_form

    if ig_dm_form.start(
        db,
        tenant_id,
        rule,
        adapter,
        recipient_id=recipient_id,
        guest_id=guest_id,
        conversation_id=conversation_id,
        guest=guest,
    ):
        db.commit()
        return True
    _send_final(
        db,
        tenant_id,
        rule,
        adapter,
        recipient_id=recipient_id,
        guest_id=guest_id,
        conversation_id=conversation_id,
        guest=guest,
        ctx=ctx,
    )
    return True


def _send_final(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    adapter,
    *,
    recipient_id: str,
    guest_id: str | None,
    conversation_id: str | None,
    guest,
    ctx: dict,
) -> None:
    cfg = rule.action_config or {}
    from app.services import ig_automation_copy as copy_rules

    text, _changes = copy_rules.prepare_dm(_render(cfg.get("message") or "", guest), _keep_words(db, tenant_id))
    button = cfg.get("button") or {}
    try:
        if button.get("url"):
            url = tracked_url(db, tenant_id, rule.id, button["url"])
            try:
                result = adapter.send_link_button(recipient_id, text, button.get("title") or "Open", url)
            except Exception as exc:  # noqa: BLE001 -- template refused: plain text with the link still works
                logger.warning("ig_automation_button_refused rule=%s: %s", rule.id, exc)
                text = f"{text}\n{url}"
                result = adapter.send_text(recipient_id, text)
        else:
            result = adapter.send_text(recipient_id, text)
    except Exception as exc:  # noqa: BLE001
        log_event(db, tenant_id, rule.id, "dm_failed", guest_id, detail=str(exc))
        _log_run(db, tenant_id, rule, "failed", f"Send failed: {exc}", ctx)
        db.commit()
        return
    _record(db, tenant_id, conversation_id, text, result, rule.id)
    log_event(db, tenant_id, rule.id, "link_sent", guest_id)  # "the final message went out" (with or without a link)
    _log_run(db, tenant_id, rule, "success", f"Sent: {text[:100]}", ctx)
    db.commit()
    from app.services import ig_sequence

    ig_sequence.begin(rule, tenant_id, recipient_id=recipient_id, guest_id=guest_id, conversation_id=conversation_id)
