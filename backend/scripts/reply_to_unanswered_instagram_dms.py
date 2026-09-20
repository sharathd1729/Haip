"""
Queue an AI reply for Instagram DMs that never got one.

Guests who messaged while the token was dead, the webhook was rejecting, or
the automation rule pre-empted the concierge are sitting in the inbox with
no response. This walks the unanswered threads and queues concierge_draft
for each, exactly as an inbound webhook would.

Distinct from retry_failed_instagram_dms.py: that re-sends a draft that was
already written and rejected by Meta. This one writes a reply where none
exists.

Meta's 24-hour rule still applies -- a business can only message inside 24h
of the guest's last message. Older threads are skipped by default rather
than queueing drafts that are guaranteed to fail on send; the draft would
still be written and clutter the inbox with un-sendable replies.
--include-expired queues them anyway (useful in shadow mode, where an agent
sends manually and the window is not the binding constraint).

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/reply_to_unanswered_instagram_dms.py --tenant-slug rathaa --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/reply_to_unanswered_instagram_dms.py --tenant-slug rathaa --send
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.conversation import (
    ChannelType, Conversation, Message, MessageDirection,
)
from app.models.tenant import Tenant

WINDOW = timedelta(hours=24)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tenant-slug", required=True)
    p.add_argument("--days", type=int, default=7,
                   help="only consider threads whose last guest message is newer than this")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--send", action="store_true", help="actually queue the drafts")
    p.add_argument("--include-expired", action="store_true",
                   help="also queue threads outside Meta's 24h window")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    if args.send and args.dry_run:
        print("Pass either --dry-run or --send, not both.", file=sys.stderr)
        sys.exit(1)
    if not args.send:
        print(">>> DRY RUN -- nothing queued. Re-run with --send.\n")

    now = datetime.now(timezone.utc)
    horizon = now - timedelta(days=args.days)

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
            sys.exit(1)

        convs = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant.id,
                Conversation.channel == ChannelType.INSTAGRAM,
            )
            .all()
        )

        eligible, expired, skipped_off = [], [], 0

        for conv in convs:
            msgs = (
                db.query(Message)
                .filter(Message.conversation_id == conv.id, Message.is_internal.is_(False))
                .order_by(Message.created_at.desc())
                .all()
            )
            if not msgs:
                continue

            newest = msgs[0]
            # "Unanswered" == the guest spoke last. If our own message is the
            # newest, the thread has been handled (by bot or agent) even if
            # that reply later failed -- retry_failed_instagram_dms.py owns
            # that case, and queueing a second draft here would double-reply.
            if newest.direction != MessageDirection.INBOUND:
                continue

            last_in = _aware(newest.created_at)
            if last_in < horizon:
                continue

            # ai_mode "off" is an explicit per-thread instruction not to draft.
            if getattr(conv, "ai_mode", None) == "off":
                skipped_off += 1
                continue

            entry = (conv, newest, last_in)
            (eligible if now - last_in <= WINDOW else expired).append(entry)

        eligible.sort(key=lambda e: e[2])
        expired.sort(key=lambda e: e[2], reverse=True)

        print(f"Instagram threads where the guest spoke last (≤{args.days}d): "
              f"{len(eligible) + len(expired)}")
        print(f"  inside Meta's 24h window : {len(eligible)}")
        print(f"  outside the window       : {len(expired)}")
        if skipped_off:
            print(f"  skipped (ai_mode=off)    : {skipped_off}")
        print()

        targets = list(eligible)
        if args.include_expired:
            targets += expired
            print("--include-expired set: drafts will be written for out-of-window "
                  "threads too; Meta will refuse the automatic send.\n")
        if args.limit:
            targets = targets[: args.limit]

        if not targets:
            print("Nothing to do.")
            return

        for conv, msg, last_in in targets:
            age = (now - last_in).total_seconds() / 3600
            body = (msg.body or "")[:70].replace("\n", " ") or "[media]"
            flag = "" if age <= 24 else "  [OUTSIDE WINDOW]"
            print(f"  conv={conv.id[:8]}  {age:5.1f}h ago{flag}  {body!r}")

        if not args.send:
            print(f"\nWould queue {len(targets)} draft(s). Re-run with --send.")
            return

        from app.services.concierge_service import mark_pending_draft
        from app.workers.tasks.concierge_draft import concierge_draft

        queued = 0
        for conv, msg, _last_in in targets:
            # Same handshake the webhook path uses, so the debounce/staleness
            # checks inside concierge_draft behave identically.
            mark_pending_draft(tenant.id, conv.id, msg.id)
            concierge_draft.delay(
                message_id=msg.id, conversation_id=conv.id, tenant_id=tenant.id,
            )
            queued += 1

        print(f"\nQueued {queued} draft(s).")
        print("Watch: docker compose -f docker-compose.prod.yml logs -f worker | grep -i concierge")
        print("In autonomous mode these send once drafted; in shadow mode they "
              "wait for an agent in the inbox.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
