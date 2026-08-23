"""
Read-only diagnostic: dump a guest's phone field and every identity signal
on record for them, sorted by confidence/recency -- to see why the phone
shown in Guest Overview can differ from the number a conversation is
actually coming in on (reported live: "Sharath" WhatsApp conversation
shows a different phone than the WA number he's messaging from).

Run:
  cd backend && python scripts/inspect_guest_phone_signals.py --name Sharath
  cd backend && python scripts/inspect_guest_phone_signals.py --guest-id <id>
"""
import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.conversation import Conversation, ChannelType


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", help="Substring match on Guest.name")
    parser.add_argument("--guest-id", help="Exact guest id")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Guest)
        if args.guest_id:
            q = q.filter(Guest.id == args.guest_id)
        elif args.name:
            q = q.filter(Guest.name.ilike(f"%{args.name}%"))
        else:
            print("Pass --name or --guest-id")
            return

        guests = q.all()
        print(f"Found {len(guests)} matching guest(s)\n")

        for guest in guests:
            print(f"=== Guest {guest.id} ===")
            print(f"  name: {guest.name!r}  phone: {guest.phone!r}  tenant: {guest.tenant_id}")

            signals = (
                db.query(GuestIdentity)
                .filter_by(tenant_id=guest.tenant_id, guest_id=guest.id)
                .order_by(GuestIdentity.created_at.asc())
                .all()
            )
            print(f"  {len(signals)} identity signal(s):")
            for s in signals:
                print(f"    [{s.created_at}] type={s.identity_type} value={s.identity_value!r} "
                      f"confidence={s.confidence} source={getattr(s, 'source', '?')}")

            convos = (
                db.query(Conversation)
                .filter_by(tenant_id=guest.tenant_id, guest_id=guest.id)
                .order_by(Conversation.created_at.asc())
                .all()
            )
            print(f"  {len(convos)} conversation(s):")
            for c in convos:
                print(f"    [{c.created_at}] id={c.id} channel={c.channel}")
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
