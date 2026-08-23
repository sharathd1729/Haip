"""
One-off sweep: scan inbound Instagram DM text from the last N days for a
phone number and, where found, write it as an identity signal -- the same
extraction process_instagram_dm.py now runs on every new inbound message
(see that fix's commit) applied retroactively to messages that arrived
before the fix shipped. Confirmed live case: a guest typed their number in
chat, the AI concierge even acknowledged it, but nothing captured the
actual digits -- Guest Overview/profile completeness never reflected it.

Uses lead_auto_create.extract_phone() -- the same phonenumbers.
is_valid_number() guard as the live fix, not the loose regex alone, so a
guest typing a date or booking reference won't get written as a fake
"phone" signal.

Run:
  cd backend && python scripts/backfill_ig_phone_signals.py --days 5 [--dry-run]

Always run --dry-run first and read the output before the real pass.
"""

import sys
import os
import argparse
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.conversation import Message, Conversation, ChannelType, MessageDirection
from app.models.guest_identity import GuestIdentity, IdentityType
from app.services.lead_auto_create import extract_phone
from app.services import identity_service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5, help="Look back this many days (default 5)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be written without writing")
    args = parser.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)

    db = SessionLocal()
    try:
        rows = (
            db.query(Message, Conversation)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .filter(
                Message.direction == MessageDirection.INBOUND,
                Conversation.channel == ChannelType.INSTAGRAM,
                Message.created_at >= since,
                Message.body.isnot(None),
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        print(f"Scanning {len(rows)} inbound Instagram message(s) since {since.isoformat()}")

        found = 0
        already_had = 0
        written = 0
        for message, conversation in rows:
            body = message.body or ""
            if body.startswith("["):
                continue
            phone = extract_phone(body)
            if not phone:
                continue
            found += 1

            guest_id = conversation.guest_id
            tenant_id = conversation.tenant_id
            existing = (
                db.query(GuestIdentity)
                .filter_by(tenant_id=tenant_id, guest_id=guest_id, identity_type=IdentityType.PHONE.value)
                .first()
            )
            if existing:
                already_had += 1
                continue

            print(f"  {'[dry-run] would add' if args.dry_run else 'adding'} phone signal "
                  f"guest={guest_id} conversation={conversation.id} message={message.id} "
                  f"(extracted from message dated {message.created_at})")
            if not args.dry_run:
                identity_service.add_signal(
                    db, tenant_id, guest_id, "phone", phone, source="message_text_backfill",
                )
                db.commit()
            written += 1

        print(f"Done. Messages with a detected phone: {found}, "
              f"already had a phone signal: {already_had}, "
              f"{'would write' if args.dry_run else 'written'}: {written}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
