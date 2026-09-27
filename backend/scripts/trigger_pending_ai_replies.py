"""
One-off backfill: draft (or send) an AI reply for every guest whose last
message went unanswered.

Real incident (Ratha, Sep 2026): concierge_draft crashed silently on a
provider error (see the 2026-09-27 fix in concierge_draft.py) while Gemini
billing was blocked, so guests on WhatsApp and Instagram who wrote in during
that window got no reply at all -- not even the safe holding reply, since the
task never completed. This re-triggers concierge_draft for every conversation
whose last message is still an unanswered guest message within the window,
using the now-fixed drafting path (currently routed to NVIDIA, see
_TASK_ROUTES in adapters/llm/__init__.py).

A conversation only qualifies when its *very last* message is inbound --
one where the team (or the AI) already replied after the guest's last line is
left alone, even if that reply came after a long gap.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/trigger_pending_ai_replies.py --tenant-slug rathaa --hours 24 --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/trigger_pending_ai_replies.py --tenant-slug rathaa --hours 24 --apply
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# `python3 scripts/foo.py` puts scripts/ on sys.path, not the project root,
# so `import app` fails with ModuleNotFoundError. Put the root on the path
# ourselves so the documented invocation works without the caller having to
# remember PYTHONPATH.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.tenant import Tenant


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--hours", type=float, default=24, help="how far back to look (default 24)")
    parser.add_argument("--channel", choices=["whatsapp", "instagram", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="cap how many conversations are queued")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="only list what would be triggered")
    mode.add_argument("--apply", action="store_true", help="actually queue the drafts")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
            return 1
        set_tenant_context(db, tenant.id)

        channels = [ChannelType.WHATSAPP, ChannelType.INSTAGRAM] if args.channel == "all" else [ChannelType(args.channel)]
        convs = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant.id,
                Conversation.channel.in_(channels),
                Conversation.is_open.is_(True),
                Conversation.ai_mode != "off",
            )
            .all()
        )

        due: list[tuple[Conversation, Message]] = []
        skipped_no_messages = skipped_already_answered = skipped_too_old = 0

        for conv in convs:
            last = db.query(Message).filter_by(conversation_id=conv.id).order_by(Message.created_at.desc()).first()
            if not last:
                skipped_no_messages += 1
                continue
            if last.direction != MessageDirection.INBOUND:
                skipped_already_answered += 1
                continue
            if _aware(last.created_at) < since:
                skipped_too_old += 1
                continue
            due.append((conv, last))

        due.sort(key=lambda pair: pair[1].created_at)
        if args.limit:
            due = due[: args.limit]

        print(f"Tenant: {tenant.slug} ({tenant.id})")
        print(f"Window: last {args.hours}h (since {since.isoformat()})")
        print(f"Open conversations checked: {len(convs)}")
        print(f"  already answered / no inbound pending: {skipped_already_answered}")
        print(f"  no messages at all:                    {skipped_no_messages}")
        print(f"  last message older than the window:    {skipped_too_old}")
        print(f"Due for a reply: {len(due)}\n")

        for conv, last in due:
            age = round((now - _aware(last.created_at)).total_seconds() / 3600, 1)
            print(f"  {conv.channel.value:9s} conv={conv.id}  guest={conv.guest_id}  waiting {age}h  \"{(last.body or '')[:60]}\"")

        if not args.dry_run:
            from app.services.concierge_service import mark_pending_draft
            from app.workers.tasks.concierge_draft import concierge_draft
            for conv, last in due:
                # Same debounce marker the normal ingestion path sets, so
                # concierge_draft's own staleness check (is_latest_pending_draft)
                # treats this as the current run rather than superseding itself.
                mark_pending_draft(tenant.id, conv.id, last.id)
                # No explicit queue= -- celery_app.py already routes this task
                # name to the "whatsapp" queue for every channel, including
                # Instagram; overriding it here risks sending it somewhere
                # nothing is consuming.
                concierge_draft.delay(message_id=last.id, conversation_id=conv.id, tenant_id=tenant.id)
            print(f"\nQueued {len(due)} draft(s).")
        else:
            print("\n>>> DRY RUN -- nothing queued. Re-run with --apply to queue these.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
