"""
One-off backfill: re-send Instagram DM replies that Meta rejected while the
access token was expired.

Ratha's Instagram token expired 10-Sep-2026 16:03 PDT. The concierge kept
drafting replies within ~15s of every inbound DM, but Meta refused each one
("Error validating access token: Session has expired") and the message was
marked FAILED. Nothing retries a FAILED message, so once the token was
renewed those drafts just sat there and the guests never heard back.

This re-queues each undelivered draft through the normal send path
(send_instagram_dm), so all the usual guards still apply -- identity lookup,
integration checks, retry/backoff, and the 24h-window handling.

IMPORTANT -- Meta's 24-hour messaging window:
  A business can only reply inside 24h of the guest's last message. Anything
  older is refused by Meta no matter how valid the token is, and only a new
  inbound message from that guest can reopen it. This script therefore skips
  conversations outside the window by default rather than generating a pile
  of guaranteed failures. --include-expired forces the attempt if you want
  the rejections recorded.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/retry_failed_instagram_dms.py --tenant-slug rathaa --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/retry_failed_instagram_dms.py --tenant-slug rathaa --send
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.conversation import (
    ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection,
)
from app.models.tenant import Tenant
from app.workers.tasks.send_instagram_dm import send_instagram_dm

WINDOW = timedelta(hours=24)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--dry-run", action="store_true", help="list only (default)")
    parser.add_argument("--send", action="store_true", help="actually re-queue the sends")
    parser.add_argument("--include-expired", action="store_true",
                        help="also attempt conversations outside Meta's 24h window")
    parser.add_argument("--limit", type=int, default=0, help="cap how many are queued")
    args = parser.parse_args()

    if args.send and args.dry_run:
        print("Pass either --dry-run or --send, not both.", file=sys.stderr)
        sys.exit(1)
    if not args.send:
        print(">>> DRY RUN -- nothing will be sent. Re-run with --send to deliver.\n")

    now = datetime.now(timezone.utc)
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

        eligible, expired, nothing_to_send = [], [], 0

        for conv in convs:
            msgs = (
                db.query(Message)
                .filter(Message.conversation_id == conv.id, Message.is_internal.is_(False))
                .order_by(Message.created_at.desc())
                .all()
            )
            if not msgs:
                continue

            last_inbound = next((m for m in msgs if m.direction == MessageDirection.INBOUND), None)
            if last_inbound is None:
                continue

            newest_outbound = next((m for m in msgs if m.direction == MessageDirection.OUTBOUND), None)
            # channel_message_id is Meta's own id -- its absence is the only
            # reliable proof the message never actually landed.
            delivered = bool(newest_outbound and newest_outbound.channel_message_id)
            if delivered and msgs[0].direction == MessageDirection.OUTBOUND:
                continue  # already answered, nothing owed

            if newest_outbound is None or not (newest_outbound.body or "").strip():
                nothing_to_send += 1
                continue

            entry = (conv, newest_outbound, _aware(last_inbound.created_at))
            if now - entry[2] <= WINDOW:
                eligible.append(entry)
            else:
                expired.append(entry)

        eligible.sort(key=lambda e: e[2])
        expired.sort(key=lambda e: e[2], reverse=True)

        print(f"Instagram conversations awaiting a reply: {len(eligible) + len(expired)}")
        print(f"  inside Meta's 24h window : {len(eligible)}")
        print(f"  outside the window       : {len(expired)}")
        if nothing_to_send:
            print(f"  skipped (no draft to send): {nothing_to_send}")
        print()

        targets = list(eligible)
        if args.include_expired:
            targets += expired
            print("--include-expired set: attempting out-of-window sends too "
                  "(Meta will refuse these).\n")
        if args.limit:
            targets = targets[: args.limit]

        if not targets:
            print("Nothing to do.")
            return

        queued = 0
        for conv, msg, last_in in targets:
            age_h = (now - last_in).total_seconds() / 3600
            preview = (msg.body or "")[:70].replace("\n", " ")
            flag = "" if age_h <= 24 else "  [OUTSIDE WINDOW]"
            print(f"  conv={conv.id[:8]} msg={msg.id[:8]} last_inbound={age_h:5.1f}h ago{flag}")
            print(f"      {preview!r}")

            if not args.send:
                continue

            # Reset the failed state so the send path treats this as a fresh
            # attempt rather than something already given up on.
            msg.delivery_state = MessageDeliveryState.QUEUED
            msg.delivery_error = None
            db.commit()

            send_instagram_dm.delay(message_id=msg.id, tenant_id=tenant.id)
            queued += 1

        print()
        if args.send:
            print(f"Queued {queued} message(s). Watch the worker log for results:")
            print("  docker compose -f docker-compose.prod.yml logs -f worker | grep -i instagram")
        else:
            print(f"Would queue {len(targets)} message(s). Re-run with --send to deliver.")

        if expired and not args.include_expired:
            print(f"\n{len(expired)} conversation(s) are past Meta's 24h window and were skipped.")
            print("Only a fresh inbound message from those guests can reopen them.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
