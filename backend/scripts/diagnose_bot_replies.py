"""Read-only: why did the bot not send (or not deliver) a reply?  Writes NOTHING.

Looks at one tenant over the last N days and prints
  * the AI mode per channel (shadow = drafts wait for a person, autonomous = sends above the confidence floor, off) and the kill switch,
  * guest messages still unanswered (no staff or AI reply after the guest's last message), oldest first,
  * what happened to every AI draft: sent by the bot, waiting for review, approved, rejected, and how each one delivered,
  * the reasons drafts were held back (the AI's own "needs a human" reasons, guards that fired, provider failures),
  * delivery errors from Meta (expired token, outside the 24-hour window, template needed ...).

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/diagnose_bot_replies.py --tenant-slug rathaa
    docker compose -f docker-compose.prod.yml exec api python3 scripts/diagnose_bot_replies.py --tenant-slug rathaa --days 14 --show 25
"""
import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.conversation import Conversation, Message, MessageDirection  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import ai_mode_service  # noqa: E402

HOLDING = "let me check and get right back to you"


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _enum(v):
    return str(getattr(v, "value", v))


def reason_group(reason: str) -> list[str]:
    """Split a stored reason ("a; b: detail") into short groups so counts add up: "price leak", "escalation", "AI reply generation failed"."""
    out = []
    for part in (reason or "").split("; "):
        part = part.strip()
        if not part:
            continue
        part = re.sub(r"\(.*", "", part)          # drop the parenthesised detail (error text, matched phrase)
        part = re.sub(r"['\"].*", "", part)       # drop quoted matches
        out.append(part.split(":")[0].strip()[:70] or "unspecified")
    return out


def error_group(err: str) -> str:
    e = (err or "").lower()
    for key, label in (("expired", "access token expired"), ("session has expired", "access token expired"), ("24", "outside the 24-hour window"),
                       ("template", "template needed"), ("rate", "rate limited by Meta"), ("permission", "missing permission"),
                       ("not a valid", "invalid recipient"), ("timeout", "timeout"), ("connection", "connection error")):
        if key in e:
            return label
    return (err or "unknown")[:80]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--show", type=int, default=15, help="how many unanswered conversations to list")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        tid = tenant.id
        since = datetime.now(timezone.utc) - timedelta(days=args.days)
        print(f"== {tenant.name} · last {args.days} day(s) · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC ==\n")

        print("AI mode")
        print(f"  kill switch: {'ON (bot never sends)' if getattr(tenant, 'ai_kill_switch', False) else 'off'}")
        for ch, col in (("whatsapp", "wa"), ("instagram", "ig")):
            mode = getattr(tenant, f"{col}_ai_mode_default", None)
            thr = getattr(tenant, f"{col}_ai_confidence_threshold", None)
            print(f"  {ch:10} mode={mode or 'shadow'}  confidence floor={thr if thr is not None else 0.78}")
        print("  (shadow = every reply waits for a person; autonomous = the bot sends when confident and no guard fired)\n")

        drafts = (db.query(Message).filter(Message.tenant_id == tid, Message.is_ai_generated.is_(True), Message.direction == MessageDirection.OUTBOUND,
                                           Message.created_at >= since).all())
        print(f"AI drafts: {len(drafts)}")
        sent_bot = [m for m in drafts if m.sent_autonomously]
        waiting = [m for m in drafts if not m.sent_autonomously and m.was_approved is None]
        approved = [m for m in drafts if not m.sent_autonomously and m.was_approved is True]
        rejected = [m for m in drafts if m.was_approved is False]
        holding = [m for m in drafts if HOLDING in (m.body or "").lower()]
        print(f"  sent by the bot itself : {len(sent_bot)}")
        print(f"  approved by a person   : {len(approved)}")
        print(f"  waiting for review     : {len(waiting)}   <- these never reach the guest until someone approves")
        print(f"  rejected               : {len(rejected)}")
        print(f"  generic holding reply  : {len(holding)}   <- the AI could not produce a real answer (provider error, timeout, or no usable output)")
        by_state = Counter(_enum(m.delivery_state) for m in drafts if m.sent_autonomously or m.was_approved)
        if by_state:
            print("  delivery of the ones meant to send: " + ", ".join(f"{k}={v}" for k, v in sorted(by_state.items())))

        reasons = Counter()
        for m in drafts:
            for g in reason_group(m.ai_needs_human_reason or ""):
                reasons[g] += 1
        print("\nWhy drafts were held back or flagged (a draft can have several reasons)")
        for g, n in reasons.most_common(12):
            print(f"  {n:4}  {g}")
        if not reasons:
            print("  none recorded")

        out_errs = (db.query(Message.delivery_error).filter(Message.tenant_id == tid, Message.direction == MessageDirection.OUTBOUND,
                                                           Message.delivery_error.isnot(None), Message.created_at >= since).all())
        all_errs = Counter(error_group(e) for (e,) in out_errs)
        print("\nDelivery errors on ALL outbound messages (AI and staff)")
        for g, n in all_errs.most_common(10):
            print(f"  {n:4}  {g}")
        if not all_errs:
            print("  none")

        # Unanswered: the guest's last message is newer than anything we sent in that conversation.
        convs = db.query(Conversation).filter(Conversation.tenant_id == tid, Conversation.is_open.is_(True), Conversation.is_sample.is_(False)).all()
        waiting_rows = []
        for c in convs:
            last_in = (db.query(func.max(Message.created_at)).filter(Message.conversation_id == c.id, Message.direction == MessageDirection.INBOUND,
                                                                     Message.is_internal.is_(False)).scalar())
            last_in = _aware(last_in)
            if last_in is None or last_in < since:
                continue
            last_out = (db.query(func.max(Message.created_at)).filter(Message.conversation_id == c.id, Message.direction == MessageDirection.OUTBOUND,
                                                                      Message.is_internal.is_(False),
                                                                      (Message.delivery_state.is_(None)) | (Message.delivery_state.notin_(["failed", "rejected"])),
                                                                      # an AI draft nobody approved is not a reply: the guest never saw it
                                                                      Message.is_ai_generated.isnot(True) | Message.sent_autonomously.is_(True) | Message.was_approved.is_(True)).scalar())
            last_out = _aware(last_out)
            if last_out is not None and last_out >= last_in:
                continue
            latest_draft = (db.query(Message).filter(Message.conversation_id == c.id, Message.is_ai_generated.is_(True)).order_by(Message.created_at.desc()).first())
            waiting_rows.append((last_in, c, latest_draft))
        waiting_rows.sort(key=lambda r: r[0])
        print(f"\nGuests still waiting for a reply: {len(waiting_rows)}")
        now = datetime.now(timezone.utc)
        for last_in, c, d in waiting_rows[: args.show]:
            hours = (now - last_in).total_seconds() / 3600
            if d is None:
                why = "no AI draft was ever made (AI off for this thread, or the draft task never ran)"
            elif d.sent_autonomously:
                why = f"bot sent, delivery={_enum(d.delivery_state)}" + (f" ({error_group(d.delivery_error)})" if d.delivery_error else "")
            elif d.was_approved is None:
                why = "draft is waiting for review" + (f": {d.ai_needs_human_reason[:90]}" if d.ai_needs_human_reason else "")
            else:
                why = f"draft was {'approved' if d.was_approved else 'rejected'}, delivery={_enum(d.delivery_state)}"
            print(f"  {hours:6.1f}h  {_enum(c.channel):9} {c.id[:8]}  {why}")
        db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
