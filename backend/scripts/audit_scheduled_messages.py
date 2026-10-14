"""Read-only audit of messages that carry a `scheduled_for` time, run BEFORE any scheduled-send task is switched on.

Why this exists: `Message.scheduled_for` has been accepted by the API and offered by the inbox for a long time, but no task has
ever sent such a message. Every row that was ever scheduled is therefore still unsent. A sender that simply sends "everything due"
would deliver all of them at once, some weeks late. This script classifies every such row so a person can decide what to do with
each class; it changes nothing.

    docker compose -f docker-compose.prod.yml exec api python scripts/audit_scheduled_messages.py
    ... --tenant <tenant_id>       one tenant
    ... --ids                      also list message ids per class (ids only, never message text or phone numbers)

Safety: one transaction opened READ ONLY and always rolled back; SELECTs only; a statement timeout on PostgreSQL. Output is counts
and (with --ids) ids. No message body, name or phone number is printed.

Classes (first match wins):
  internal_note       an internal note; never sent to a guest
  already_handled     has a delivery state or a provider id: not a pending scheduled send
  orphan              its conversation no longer exists
  unparseable         `scheduled_for` is not a valid ISO date-time
  future              due later than now: eligible when due
  due_within_grace    due now or within the grace window: the ONLY class a first sweep may pick up
  stale               due earlier than the grace window: must never be sent automatically
Flags (independent of the class):
  opted_out           the guest's marketing consent is withdrawn or they are off the WhatsApp subscriber list
  duplicate           same conversation, same text, same due minute as an earlier row
  not_outbound        direction is not outbound
`would_send_on_first_sweep` = due_within_grace with no flags.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GRACE = timedelta(minutes=15)
DEFAULT_TZ = "Asia/Kolkata"


def parse_scheduled(value: Optional[str], tz_name: Optional[str]) -> Optional[datetime]:
    """ISO date-time -> aware UTC datetime. A value with no offset is read in the tenant's timezone."""
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name or DEFAULT_TZ))
        except Exception:
            dt = dt.replace(tzinfo=ZoneInfo(DEFAULT_TZ))
    return dt.astimezone(timezone.utc)


def classify(row: dict, now: datetime, grace: timedelta = GRACE) -> str:
    """Class of one row (see module docstring). `row` needs: is_internal, delivery_state, channel_message_id,
    conversation_exists, due (aware UTC datetime or None)."""
    if row.get("is_internal"):
        return "internal_note"
    if row.get("delivery_state") not in (None, "") or row.get("channel_message_id"):
        return "already_handled"
    if not row.get("conversation_exists", True):
        return "orphan"
    due = row.get("due")
    if due is None:
        return "unparseable"
    if due > now:
        return "future"
    if now - due <= grace:
        return "due_within_grace"
    return "stale"


def audit(db, now: Optional[datetime] = None, tenant_id: Optional[str] = None, grace: timedelta = GRACE) -> dict:
    """Classify every message with a `scheduled_for`. Returns {"classes": Counter, "flags": Counter, "ids": {...},
    "by_tenant": {...}, "would_send_on_first_sweep": int}. Reads only."""
    from app.api.v1.endpoints.messaging import WASubscriber
    from app.models.consent import Consent
    from app.models.conversation import Conversation, Message
    from app.models.guest import Guest
    from app.models.tenant import Tenant

    now = now or datetime.now(timezone.utc)
    q = db.query(Message).filter(Message.scheduled_for.isnot(None), Message.scheduled_for != "")
    if tenant_id:
        q = q.filter(Message.tenant_id == tenant_id)
    messages = q.order_by(Message.tenant_id, Message.conversation_id, Message.scheduled_for, Message.created_at).all()

    tz_by_tenant = {t.id: getattr(t, "timezone", None) for t in db.query(Tenant.id, Tenant.timezone).all()} \
        if hasattr(Tenant, "timezone") else {}
    conv_ids = {m.conversation_id for m in messages}
    convs = {c.id: c for c in db.query(Conversation).filter(Conversation.id.in_(conv_ids)).all()} if conv_ids else {}
    guest_ids = {c.guest_id for c in convs.values()}
    withdrawn = {
        (c.tenant_id, c.guest_id)
        for c in db.query(Consent).filter(Consent.guest_id.in_(guest_ids), Consent.scope == "marketing", Consent.granted.is_(False)).all()
    } if guest_ids else set()
    phones = {g.id: (g.tenant_id, g.phone) for g in db.query(Guest).filter(Guest.id.in_(guest_ids)).all()} if guest_ids else {}
    off_list = {
        (s.tenant_id, s.phone) for s in db.query(WASubscriber).filter(WASubscriber.opted_in.is_(False)).all()
    } if phones else set()

    classes: Counter = Counter()
    flags: Counter = Counter()
    ids: dict[str, list[str]] = defaultdict(list)
    by_tenant: dict[str, Counter] = defaultdict(Counter)
    seen: set[tuple] = set()
    first_sweep = 0

    for m in messages:
        due = parse_scheduled(m.scheduled_for, tz_by_tenant.get(m.tenant_id))
        conv = convs.get(m.conversation_id)
        state = getattr(m.delivery_state, "value", m.delivery_state)
        cls = classify({
            "is_internal": bool(m.is_internal), "delivery_state": state, "channel_message_id": m.channel_message_id,
            "conversation_exists": conv is not None, "due": due,
        }, now, grace)
        row_flags = []
        if conv is not None:
            if (m.tenant_id, conv.guest_id) in withdrawn or (phones.get(conv.guest_id) in off_list):
                row_flags.append("opted_out")
        direction = getattr(m.direction, "value", m.direction)
        if str(direction).lower() != "outbound":
            row_flags.append("not_outbound")
        if due is not None:
            key = (m.conversation_id, (m.body or "").strip(), due.replace(second=0, microsecond=0))
            if key in seen:
                row_flags.append("duplicate")
            seen.add(key)

        classes[cls] += 1
        by_tenant[m.tenant_id][cls] += 1
        ids[cls].append(m.id)
        for f in row_flags:
            flags[f] += 1
            ids[f"flag:{f}"].append(m.id)
        if cls == "due_within_grace" and not row_flags:
            first_sweep += 1
            ids["would_send_on_first_sweep"].append(m.id)

    return {"classes": classes, "flags": flags, "ids": dict(ids), "by_tenant": dict(by_tenant),
            "would_send_on_first_sweep": first_sweep, "total": len(messages), "as_of": now.isoformat()}


def _print(report: dict, show_ids: bool) -> None:
    print(f"Scheduled-message audit as of {report['as_of']}  (grace {int(GRACE.total_seconds() // 60)} min)")
    print(f"Rows with a scheduled_for: {report['total']}")
    for cls in ("future", "due_within_grace", "stale", "unparseable", "already_handled", "internal_note", "orphan"):
        print(f"  {cls:<18} {report['classes'].get(cls, 0)}")
    for f in ("opted_out", "duplicate", "not_outbound"):
        print(f"  flag {f:<13} {report['flags'].get(f, 0)}")
    print(f"Would be sent by a first sweep: {report['would_send_on_first_sweep']}")
    print(f"Stale rows that must NOT be sent automatically: {report['classes'].get('stale', 0)}")
    if len(report["by_tenant"]) > 1:
        print("By tenant:")
        for tid, c in sorted(report["by_tenant"].items()):
            print(f"  {tid}: " + ", ".join(f"{k}={v}" for k, v in sorted(c.items())))
    if show_ids:
        for k, v in sorted(report["ids"].items()):
            print(f"[{k}] " + ", ".join(v[:200]) + (" ..." if len(v) > 200 else ""))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", help="limit to one tenant id")
    ap.add_argument("--ids", action="store_true", help="also print message ids per class")
    args = ap.parse_args(argv)

    from sqlalchemy import text
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
            db.execute(text("SET LOCAL statement_timeout = '30s'"))
        _print(audit(db, tenant_id=args.tenant), args.ids)
    finally:
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
