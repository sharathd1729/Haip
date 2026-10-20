"""Give guests the phone number they already typed in a chat message but HAIP did not capture.

Until Oct 2026 the chat phone capture took only the first run of digits in a message, so "9876543210 21/10 to 22/10",
"24 10 2026 to 26 10 2026, ph 9876543210", "+91 9876543210 2 adults" and "98765.43210" were missed: the guest's number sat in
the transcript, they were never counted as a lead and the bot kept asking for it. This re-reads recent INBOUND messages of
guests who still have no phone signal and attaches the first number found, through the same code the live path now uses
(app/services/chat_phone_capture.py -> identity_service.add_signal).

What it changes (a DRY RUN unless you pass --apply; nothing is written in a dry run):
  * one phone signal per guest (the first number in their earliest message that has one), dated at that message, so the
    person counts as a lead from the day they actually shared it, not from today;
  * guests.phone when empty; an enquiry still in the "no phone yet" entry stage moves to the valid-lead entry stage;
    an open "Guest declined phone number" task on that conversation is closed;
  * if another guest already has that number, the two are merged (logged in guest_merge_events and reversible).
Never touched: personal-WhatsApp mirrored chats (they become leads only when the person writes live), outbound messages,
guests that already have a phone or WhatsApp number. Phone numbers are never printed, only a short hash.

Usage (inside the API container):
    python3 scripts/backfill_chat_phones.py --tenant-slug rathaa [--days 90]
    ... same command with --apply to write.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.conversation import Conversation, Message, MessageDirection  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.guest_identity import GuestIdentity  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import chat_phone_capture, phone_identity  # noqa: E402
from app.services.identity_service import _phone_token  # noqa: E402


def run(db, tenant_id: str, *, days: int = 90, apply: bool = False) -> dict:
    out = {"guests_without_phone": 0, "messages_scanned": 0, "phones_found": 0, "would_merge": 0, "applied": 0, "failed": 0,
           "found": []}
    region = chat_phone_capture.region_for(db, tenant_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with_phone = {g for (g,) in db.query(GuestIdentity.guest_id).filter(
        GuestIdentity.tenant_id == tenant_id, GuestIdentity.identity_type.in_(chat_phone_capture._PHONE_TYPES))}
    rows = (
        db.query(Message, Conversation)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(Message.tenant_id == tenant_id, Conversation.tenant_id == tenant_id,
                Message.direction == MessageDirection.INBOUND, Message.created_at >= since,
                (Conversation.source.is_(None)) | (Conversation.source != "personal_bridge"))
        .order_by(Message.created_at.asc())
        .all()
    )
    seen_guests: set[str] = set()
    done: set[str] = set()
    for msg, conv in rows:
        gid = conv.guest_id
        if not gid or gid in with_phone or gid in done:
            continue
        if gid not in seen_guests:
            seen_guests.add(gid)
        body = msg.body or ""
        if not body or body.startswith("["):
            continue
        out["messages_scanned"] += 1
        found = phone_identity.find_phones(body, region)
        if not found:
            continue
        done.add(gid)
        out["phones_found"] += 1
        phone = found[0]
        owner = (db.query(GuestIdentity.guest_id)
                 .filter(GuestIdentity.tenant_id == tenant_id, GuestIdentity.identity_type.in_(chat_phone_capture._PHONE_TYPES),
                         GuestIdentity.identity_value == phone).first())
        if owner and owner[0] != gid:
            out["would_merge"] += 1
        out["found"].append({"guest_id": gid, "phone_token": _phone_token(phone), "message_at": msg.created_at.isoformat()
                             if msg.created_at else None, "merges_with_existing_guest": bool(owner and owner[0] != gid)})
        if not apply:
            continue
        if db.query(Guest.id).filter_by(id=gid, tenant_id=tenant_id, is_deleted=False).first() is None:
            continue
        try:
            when = msg.created_at if (msg.created_at is None or msg.created_at.tzinfo) else msg.created_at.replace(tzinfo=timezone.utc)
            chat_phone_capture.capture_from_text(db, tenant_id, gid, body, source="message_text_backfill", conversation=conv,
                                                 observed_at=when, region=region)
            db.commit()
            out["applied"] += 1
        except Exception as exc:  # noqa: BLE001 -- one bad row must not stop the run
            db.rollback()
            out["failed"] += 1
            print(f"  failed for guest {gid}: {str(exc)[:160]}")
    out["guests_without_phone"] = len(seen_guests)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--days", type=int, default=90, help="how far back to read messages (default 90)")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()
    if args.days < 1 or args.days > 730:
        raise SystemExit("--days must be between 1 and 730")
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        from app.core.database import set_tenant_context
        set_tenant_context(db, tenant.id)
        out = run(db, tenant.id, days=args.days, apply=args.apply)
        print("APPLIED" if args.apply else "DRY RUN (nothing written; add --apply)")
        for key in ("guests_without_phone", "messages_scanned", "phones_found", "would_merge", "applied", "failed"):
            print(f"  {key}: {out[key]}")
        for row in out["found"][:200]:
            print(f"  guest {row['guest_id']}  phone#{row['phone_token']}  shared {row['message_at']}"
                  + ("  (merges with an existing guest)" if row["merges_with_existing_guest"] else ""))
        if not args.apply:
            db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
