"""
WhatsApp overview, the automatic part: what HAIP sent on its own, apart from campaigns.

  team alerts      playbook_actions "staff_wa" (template to a staff member's own number) and "push" (app
                   notification): new-lead alerts, escalations, consult alerts, call-me-back taps, digests.
                   Delivery comes from the alert's own receipt (lead_alert_sender.apply_status_callback keeps the
                   furthest Meta status in payload["delivery"]); there is no Message row for staff.
  guest messages   playbook_actions "wa_template" / "wa_text" (missed call, tried calling, follow-ups, win back).
                   Delivery comes from the linked Message row's delivery_state, as for any inbox message.

Same period rule as the campaign overview (wa_analytics_service): India calendar days, a row belongs to the day it
was created. Numbers are counted the same way too (sent includes delivered and read).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.conversation import Message
from app.models.lead_workflow import PlaybookAction
from app.models.user import User
from app.services.wa_analytics_service import _aware, _ist_midnight, _totals
from app.services.wa_campaign_delivery import GROUP_LABELS, describe_error
from app.services.wa_campaign_schedule import IST

MAX_ROWS = 50_000
TEAM_ACTIONS = ("staff_wa", "push")
GUEST_ACTIONS = ("wa_template", "wa_text")
_ERR = re.compile(r"^\s*(?:Meta\s+)?(\d+)\s*:\s*(.*)$", re.S)
# A failed team alert is always pushed to the person instead (lead_alert_service.push_fallback / the caller), so the
# guest-marketing wording describe_error has for these codes would mislead here.
_STAFF_WORDS = {
    "131049": (
        "Meta limited messages to this person",
        "Meta limited messages to this person; alerts fell back to the app.",
    ),
}


def _period(days: int, now: datetime | None) -> tuple[int, str, str, datetime, datetime]:
    now = now or datetime.now(UTC)
    days = max(1, min(int(days), 365))
    today = now.astimezone(IST).date()
    first = today - timedelta(days=days - 1)
    return days, first.isoformat(), today.isoformat(), _ist_midnight(first), _ist_midnight(today + timedelta(days=1))


def _reason_group(groups: dict, text: str | None, staff: bool) -> None:
    """Add one failure to ``groups``, keyed by Meta's code when the text has one ("Meta 131049: ..." / "131049: ...")."""
    m = _ERR.match(text or "")
    code, rest = (m.group(1), m.group(2)) if m else (None, text)
    info = describe_error(code, rest)
    if code and staff and code in _STAFF_WORDS:
        label, reason = _STAFF_WORDS[code]
        key, hint = f"staff:{code}", None
    elif code:
        key, label, reason, hint = info.group, GROUP_LABELS.get(info.group, "Other"), info.reason, info.hint
    else:
        key, label, reason, hint = f"text:{info.reason}", "Couldn't send", info.reason, None
    if staff and hint is None and key != "staff:131049":
        hint = "The alert went to the app instead."
    g = groups.setdefault(key, {"group": key, "label": label, "count": 0, "reason": reason, "hint": hint})
    g["count"] += 1


def _rows(db: Session, tenant_id: str, actions: tuple, start: datetime, end: datetime) -> tuple[list, bool]:
    rows = (
        db.query(PlaybookAction)
        .filter(
            PlaybookAction.tenant_id == tenant_id,
            PlaybookAction.action.in_(actions),
            PlaybookAction.created_at >= start,
            PlaybookAction.created_at < end,
        )
        .order_by(PlaybookAction.created_at.desc())
        .limit(MAX_ROWS + 1)
        .all()
    )
    return rows[:MAX_ROWS], len(rows) > MAX_ROWS


def team_alerts(db: Session, tenant_id: str, start: datetime, end: datetime) -> dict:
    rows, truncated = _rows(db, tenant_id, TEAM_ACTIONS, start, end)
    wa = Counter()
    push = Counter()
    people: dict[str | None, Counter] = defaultdict(Counter)
    last: dict[str | None, datetime] = {}
    failures: dict[str, dict] = {}
    for r in rows:
        person = people[r.recipient_user_id]
        if r.status == "failed":
            person["failed"] += 1
        if r.action == "staff_wa":
            if r.status == "done":
                delivery = (r.payload or {}).get("delivery")
                wa["sent"] += 1
                wa["tracked"] += 1 if r.wa_message_id else 0
                wa["delivered"] += 1 if delivery in ("delivered", "read") else 0
                wa["read"] += 1 if delivery == "read" else 0
                person["whatsapp"] += 1
            elif r.status == "failed":
                wa["failed"] += 1
                _reason_group(failures, r.reason, staff=True)
            elif r.status in ("held", "queued"):
                wa["waiting"] += 1
        else:
            if r.status == "done":
                push["sent"] += 1
                person["push"] += 1
            elif r.status == "failed":
                push["failed"] += 1
        if r.status == "done" and r.created_at:
            at = _aware(r.created_at)
            if r.recipient_user_id not in last or at > last[r.recipient_user_id]:
                last[r.recipient_user_id] = at

    ids = [k for k in people if k]
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(ids or ["-"]))}
    person_rows = []
    for uid, c in people.items():
        u = users.get(uid) if uid else None
        person_rows.append(
            {
                "user_id": uid,
                "name": u.name if u else ("Whole team" if uid is None else "Former team member"),
                "role": (u.role.value if hasattr(u.role, "value") else str(u.role)) if u else None,
                "received": c["whatsapp"] + c["push"],
                "whatsapp": c["whatsapp"],
                "push": c["push"],
                "failed": c["failed"],
                "last_at": last[uid].isoformat() if uid in last else None,
            }
        )
    person_rows.sort(key=lambda p: (-(p["received"] + p["failed"]), p["name"]))
    return {
        "whatsapp": {
            **_totals(wa["sent"], wa["delivered"], wa["read"], wa["failed"]),
            "waiting": wa["waiting"],
            # Every sent alert carries Meta's message id, so its receipts were matched. If some did not,
            # delivered/read would undercount: the page says delivery is not tracked instead of a low rate.
            "delivery_tracked": wa["sent"] > 0 and wa["tracked"] == wa["sent"],
        },
        "push": {"sent": push["sent"], "failed": push["failed"]},
        "people": person_rows,
        "failures": sorted(failures.values(), key=lambda g: -g["count"]),
        "truncated": truncated,
    }


def guest_messages(db: Session, tenant_id: str, start: datetime, end: datetime) -> dict:
    from app.models.conversation import MessageDeliveryState as S
    from app.services import lead_playbook_catalog as cat

    rows, truncated = _rows(db, tenant_id, GUEST_ACTIONS, start, end)
    mids = [r.message_id for r in rows if r.message_id]
    msgs = {
        m.id: m
        for m in db.query(Message.id, Message.delivery_state, Message.delivery_error).filter(
            Message.tenant_id == tenant_id, Message.id.in_(mids or ["-"])
        )
    }
    total = Counter()
    per: dict[str, Counter] = defaultdict(Counter)
    skips: Counter = Counter()
    failures: dict[str, dict] = {}
    for r in rows:
        c = per[r.playbook_key]
        m = msgs.get(r.message_id) if r.message_id else None
        state = m.delivery_state if m else None
        if r.status == "skipped":
            outcome = "skipped"
            skips[(r.reason or "No reason recorded").strip()] += 1
        elif r.status == "failed" or state in (S.FAILED, S.REJECTED):
            outcome = "failed"
            _reason_group(failures, (m.delivery_error if m and m.delivery_error else None) or r.reason, staff=False)
        elif state in (S.SENT, S.DELIVERED, S.READ):
            outcome = "sent"
            for k, hit in (("delivered", state in (S.DELIVERED, S.READ)), ("read", state == S.READ)):
                if hit:
                    c[k] += 1
                    total[k] += 1
        else:
            outcome = "waiting"  # queued for Meta, or older than any receipt
        c[outcome] += 1
        total[outcome] += 1

    playbook_rows = sorted(
        [
            {
                "playbook": k,
                "name": (cat.BY_KEY.get(k) or {}).get("name", k),
                "skipped": c["skipped"],
                "waiting": c["waiting"],
                **_totals(c["sent"], c["delivered"], c["read"], c["failed"]),
            }
            for k, c in per.items()
        ],
        key=lambda p: -(p["sent"] + p["failed"] + p["skipped"]),
    )
    return {
        "totals": {
            **_totals(total["sent"], total["delivered"], total["read"], total["failed"]),
            "skipped": total["skipped"],
            "waiting": total["waiting"],
        },
        "playbooks": playbook_rows,
        "skip_reasons": [{"reason": k, "count": n} for k, n in skips.most_common(10)],
        "failures": sorted(failures.values(), key=lambda g: -g["count"]),
        "truncated": truncated,
    }


def automatic(db: Session, tenant_id: str, days: int = 30, now: datetime | None = None) -> dict:
    days, first, last, start, end = _period(days, now)
    return {
        "range": {"days": days, "from": first, "to": last},
        "team_alerts": team_alerts(db, tenant_id, start, end),
        "guest_messages": guest_messages(db, tenant_id, start, end),
    }
