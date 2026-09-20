"""
Pull Instagram DMs from Meta into the HAIP inbox.

Webhooks are the normal path, but anything Meta delivered while the
webhook was rejecting (wrong app secret) or while the token was dead is
simply gone -- Meta does not redeliver. This reads the conversations back
out of the Graph API and replays them through the same
process_instagram_dm task the webhook uses, so guests, conversations,
identity signals and dedupe all behave identically.

Messages already stored are skipped: process_instagram_dm dedupes on
channel_message_id, and this script also filters them out up front so the
dry-run count reflects real work.

Automation is suppressed by default. Replaying three days of messages
through the concierge would blast quick-replies and AI drafts at guests
whose conversations have moved on, and Meta refuses any send outside its
24h window regardless -- so it would yield noise plus failed rows. Pass
--with-replies to let the normal automation run.

Reading conversations needs Advanced Access to
instagram_business_manage_messages. An app in Development mode, or one
without that access, gets an error from Meta -- printed verbatim here
rather than swallowed, because it is the single most useful thing to see
when this comes back empty.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/import_instagram_dms.py --tenant-slug rathaa --days 3 --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/import_instagram_dms.py --tenant-slug rathaa --days 3 --send
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from app.core.database import SessionLocal
from app.core.encryption import decrypt_credentials
from app.models.conversation import ChannelType, Message
from app.models.integration import Integration
from app.models.tenant import Tenant

GRAPH = "https://graph.instagram.com/v21.0"
# messages.limit(N) is how the Graph API nests a message page inside each
# conversation; without it only a handful of message ids come back.
CONV_FIELDS = "participants,messages.limit(100){id,created_time,from,to,message}"


def _parse_ts(value):
    """Meta returns ISO-8601 with a +0000 offset (no colon)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("+0000", "+00:00"))
    except ValueError:
        return None


def _get(url, params, label):
    try:
        resp = httpx.get(url, params=params, timeout=30)
    except Exception as exc:
        print(f"  ! {label} request failed: {exc}", file=sys.stderr)
        return None
    if resp.status_code != 200:
        print(f"  ! {label} HTTP {resp.status_code}: {resp.text[:600]}", file=sys.stderr)
        return None
    return resp.json()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tenant-slug", required=True)
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--send", action="store_true", help="actually import")
    p.add_argument("--with-replies", action="store_true",
                   help="let the concierge/auto-reply run on imported messages")
    p.add_argument("--max-pages", type=int, default=20)
    p.add_argument("--fix-timestamps", action="store_true",
                   help="repair created_at on messages already imported with the "
                        "wrong time (stamped at import instead of Meta's event time)")
    args = p.parse_args()

    if args.send and args.dry_run:
        print("Pass either --dry-run or --send, not both.", file=sys.stderr)
        sys.exit(1)
    if not args.send:
        print(">>> DRY RUN -- nothing will be imported. Re-run with --send.\n")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
            sys.exit(1)

        integ = db.query(Integration).filter_by(
            tenant_id=tenant.id, kind="instagram", status="active").first()
        if not integ or not integ.credentials_kms_blob:
            print("Instagram integration not connected.", file=sys.stderr)
            sys.exit(1)

        creds = decrypt_credentials(integ.credentials_kms_blob)
        token = creds.get("access_token", "")
        ig_account_id = (integ.config or {}).get("instagram_business_account_id", "")
        if not token:
            print("No access_token stored -- reconnect via Instagram Login first.", file=sys.stderr)
            sys.exit(1)

        print(f"account @{(integ.config or {}).get('username', '?')} ({ig_account_id})")
        print(f"importing messages newer than {cutoff:%Y-%m-%d %H:%M} UTC\n")

        # ── page through conversations ────────────────────────────────────
        conversations, url, params, pages = [], f"{GRAPH}/me/conversations", {
            "fields": CONV_FIELDS, "access_token": token,
        }, 0
        while url and pages < args.max_pages:
            data = _get(url, params, "conversations")
            if data is None:
                print("\nCould not read conversations from Meta (see error above).")
                print("Most common cause: the app lacks Advanced Access to")
                print("instagram_business_manage_messages, or is still in Development mode.")
                sys.exit(1)
            conversations.extend(data.get("data", []))
            url = (data.get("paging") or {}).get("next")
            params = None  # `next` is a fully-formed URL
            pages += 1

        print(f"conversations returned: {len(conversations)}")

        # ── collect in-window inbound messages ────────────────────────────
        candidates, too_old, echoes = [], 0, 0
        for conv in conversations:
            for msg in ((conv.get("messages") or {}).get("data") or []):
                ts = _parse_ts(msg.get("created_time"))
                if ts is None or ts < cutoff:
                    too_old += 1
                    continue
                sender_id = ((msg.get("from") or {}).get("id")) or ""
                if sender_id and ig_account_id and sender_id == ig_account_id:
                    echoes += 1  # our own outbound; not an inbox item
                    continue
                candidates.append({
                    "mid": msg.get("id", ""),
                    "sender_id": sender_id,
                    "text": msg.get("message", "") or "",
                    "ts": ts,
                })

        # already stored?
        mids = [c["mid"] for c in candidates if c["mid"]]
        existing = set()
        if mids:
            for (found,) in db.query(Message.channel_message_id).filter(
                Message.tenant_id == tenant.id,
                Message.channel == ChannelType.INSTAGRAM,
                Message.channel_message_id.in_(mids),
            ).all():
                existing.add(found)

        fresh = [c for c in candidates if c["mid"] and c["mid"] not in existing]

        # ── repair mode ───────────────────────────────────────────────────
        # Messages imported before the task honoured Meta's event time all
        # carry the import time instead, so the inbox shows days-old DMs as
        # having just arrived. Re-stamp them from Meta rather than deleting
        # and re-importing, which would lose any reply already attached.
        if args.fix_timestamps:
            by_mid = {c["mid"]: c for c in candidates if c["mid"]}
            rows = db.query(Message).filter(
                Message.tenant_id == tenant.id,
                Message.channel == ChannelType.INSTAGRAM,
                Message.channel_message_id.in_(list(by_mid.keys()) or [""]),
            ).all()

            drifted = []
            for row in rows:
                truth = by_mid[row.channel_message_id]["ts"]
                current = row.created_at
                if current and current.tzinfo is None:
                    current = current.replace(tzinfo=timezone.utc)
                if current is None or abs((current - truth).total_seconds()) > 120:
                    drifted.append((row, current, truth))

            print(f"  timestamps needing repair   : {len(drifted)}")
            for row, current, truth in sorted(drifted, key=lambda r: r[2])[:40]:
                print(f"    {row.channel_message_id[:24]}  "
                      f"{current:%d-%b %H:%M} -> {truth:%d-%b %H:%M}")

            if drifted and args.send:
                for row, _current, truth in drifted:
                    row.created_at = truth
                db.flush()

                # A wrong created_at does more than reorder the inbox: the
                # conversation and the inquiry the import created were also
                # stamped at import time, so days-old DMs counted as today's
                # leads. Re-derive both from the real message times.
                from app.models.conversation import Conversation
                from app.models.inquiry import Inquiry

                conv_ids = {r.conversation_id for r, _c, _t in drifted if r.conversation_id}
                convs_fixed = inqs_fixed = 0
                for conv in db.query(Conversation).filter(Conversation.id.in_(conv_ids)).all():
                    times = [
                        m.created_at for m in db.query(Message)
                        .filter(Message.conversation_id == conv.id).all()
                        if m.created_at
                    ]
                    if not times:
                        continue
                    earliest, latest = min(times), max(times)

                    conv.last_message_at = (
                        latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
                    ).isoformat()

                    conv_created = conv.created_at
                    if conv_created and conv_created.tzinfo is None:
                        conv_created = conv_created.replace(tzinfo=timezone.utc)
                    if conv_created and conv_created > earliest:
                        conv.created_at = earliest
                        convs_fixed += 1

                    if conv.inquiry_id:
                        inq = db.query(Inquiry).filter_by(id=conv.inquiry_id).first()
                        inq_created = getattr(inq, "created_at", None)
                        if inq_created and inq_created.tzinfo is None:
                            inq_created = inq_created.replace(tzinfo=timezone.utc)
                        if inq and inq_created and inq_created > earliest:
                            inq.created_at = earliest
                            inqs_fixed += 1

                db.commit()
                print(f"\n  repaired {len(drifted)} message timestamp(s)")
                print(f"  re-dated {convs_fixed} conversation(s) and {inqs_fixed} inquiry/lead(s)")
                print("  -> the inbox re-sorts by real time, and these stop "
                      "counting as today's leads")
            elif drifted:
                print(f"\n  would repair {len(drifted)} timestamp(s), plus the "
                      "conversations and leads they created. Re-run with --send.")
            if not fresh:
                return

        print(f"  in-window inbound messages : {len(candidates)}")
        print(f"  already in HAIP            : {len(candidates) - len(fresh)}")
        print(f"  outside the {args.days}-day window  : {too_old}")
        print(f"  own outbound (skipped)     : {echoes}")
        print(f"  TO IMPORT                  : {len(fresh)}\n")

        if not fresh:
            print("Nothing to import.")
            return

        for c in sorted(fresh, key=lambda x: x["ts"]):
            preview = c["text"][:70].replace("\n", " ") or "[media/attachment]"
            print(f"  {c['ts']:%d-%b %H:%M}  {c['sender_id'][:16]:<18} {preview!r}")

        if not args.send:
            print(f"\nWould import {len(fresh)} message(s). Re-run with --send.")
            return

        from app.workers.tasks.process_instagram_dm import process_instagram_dm

        queued = 0
        for c in sorted(fresh, key=lambda x: x["ts"]):
            process_instagram_dm.delay({
                "ig_account_id": ig_account_id,
                "sender_id": c["sender_id"],
                "message_id": c["mid"],
                "text": c["text"],
                "attachments": [],
                "timestamp": int(c["ts"].timestamp() * 1000),
                "reply_to": {},
                "referral": {},
                # default: import into the inbox without waking the concierge
                "suppress_automation": not args.with_replies,
            })
            queued += 1

        print(f"\nQueued {queued} message(s) for import"
              f"{' with automation enabled' if args.with_replies else ' (automation suppressed)'}.")
        print("Watch: docker compose -f docker-compose.prod.yml logs -f worker | grep -i instagram")
    finally:
        db.close()


if __name__ == "__main__":
    main()
