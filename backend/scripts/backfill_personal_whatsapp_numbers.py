"""One-off: give the personal-WhatsApp chats already imported their phone number and real name.

The history import stored chats WhatsApp identifies only by a private id (@lid) with no number and a generic name ("WhatsApp contact").
The bridge's own database (the whatsmeow tables) already knows both: whatsmeow_lid_map (private id -> number) and whatsmeow_contacts
(names saved on the phone). This copies them onto the imported chats.

What it changes (a DRY RUN unless you pass --apply; nothing is written in a dry run):
  * guests.phone (display only) and guests.name of an imported 1:1 chat that has none / a generic one.
  * It does NOT make anyone a lead (no identity signal is added) and never overwrites a real phone or name.
  * If HAIP already knows a guest by that number (a real lead), the imported chat is moved onto that guest so there is one person.

Usage (inside the API container, against production; the bridge DB address is passed in, not read from the API's environment):
    docker compose -f docker-compose.prod.yml exec -e BRIDGE_DSN="$(grep '^WHATSAPP_BRIDGE_DB_DSN=' .env | cut -d= -f2-)" \
        api python3 scripts/backfill_personal_whatsapp_numbers.py --tenant-slug rathaa
    ... same command with --apply to write.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.conversation import ChannelType, Conversation, Message  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import whatsapp_personal_service as svc  # noqa: E402


def load_bridge_maps(dsn: str) -> tuple[dict[str, str], dict[str, str]]:
    """(lid user -> phone digits, jid -> best name) from the bridge's whatsmeow tables."""
    import psycopg2

    conn = psycopg2.connect(dsn, connect_timeout=10)
    try:
        cur = conn.cursor()
        cur.execute("SELECT lid, pn FROM whatsmeow_lid_map WHERE pn IS NOT NULL AND pn <> ''")
        lid_to_pn = {str(a): str(b) for a, b in cur.fetchall()}
        cur.execute("SELECT their_jid, full_name, push_name, business_name, first_name FROM whatsmeow_contacts")
        names: dict[str, str] = {}
        for jid, full, push, biz, first in cur.fetchall():
            best = next((n for n in (full, push, biz, first) if n), "")
            if best:
                names[str(jid)] = best
        return lid_to_pn, names
    finally:
        conn.close()


def resolve(jid: str, lid_to_pn: dict[str, str], names: dict[str, str]) -> tuple[str | None, str | None]:
    """(phone as +digits or None, best name or None) for a chat jid."""
    if not jid or "@" not in jid:
        return None, None
    user, server = jid.split("@", 1)
    digits = user if server == "s.whatsapp.net" else lid_to_pn.get(user) if server == "lid" else None
    phone = f"+{digits}" if digits else None
    # the name the phone has saved for the NUMBER beats the WhatsApp name of the hidden id
    name = (names.get(f"{digits}@s.whatsapp.net") if digits else None) or names.get(jid)
    return phone, name


def run(db, tenant_id: str, lid_to_pn: dict[str, str], names: dict[str, str]) -> dict:
    out = {"chats": 0, "phone_set": 0, "name_set": 0, "moved_to_existing_guest": 0, "merged_into_open_conversation": 0, "unresolved": 0}
    convs = (db.query(Conversation).filter(Conversation.tenant_id == tenant_id, Conversation.channel == ChannelType.WHATSAPP,
                                           Conversation.source == "personal_bridge", Conversation.channel_conversation_id.isnot(None),
                                           ~Conversation.channel_conversation_id.like("%@g.us")).all())
    for conv in convs:
        out["chats"] += 1
        guest = db.query(Guest).filter_by(id=conv.guest_id, tenant_id=tenant_id).first()
        if guest is None or (guest.phone or "").strip():
            continue                                                  # already has a number (a real lead): leave it
        phone, name = resolve(conv.channel_conversation_id, lid_to_pn, names)
        if not phone:
            out["unresolved"] += 1
            continue
        known = svc._existing_guest_by_phone(db, tenant_id, phone)
        if known and known != guest.id:
            # One person, one record. A guest can have only ONE open WhatsApp conversation, so when that lead already has one the
            # imported messages are merged into it (chronological, by their own timestamps) and the emptied imported thread is closed.
            target = (db.query(Conversation).filter(Conversation.tenant_id == tenant_id, Conversation.guest_id == known,
                                                    Conversation.channel == ChannelType.WHATSAPP, Conversation.is_open.is_(True),
                                                    Conversation.id != conv.id).first())
            if target is None:
                conv.guest_id = known
            else:
                db.query(Message).filter(Message.conversation_id == conv.id, Message.tenant_id == tenant_id).update(
                    {"conversation_id": target.id}, synchronize_session=False)
                if conv.last_message_at and (not target.last_message_at or target.last_message_at < conv.last_message_at):
                    target.last_message_at = conv.last_message_at
                conv.is_open = False
                conv.channel_conversation_id = None                   # a later live message finds the lead's own thread, not this one
                out["merged_into_open_conversation"] += 1
            out["moved_to_existing_guest"] += 1
            db.flush()
            continue
        before_name = guest.name
        svc.fill_mirror_identity(guest, phone, name)
        out["phone_set"] += 1
        out["name_set"] += int(guest.name != before_name)
    db.flush()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()
    dsn = os.environ.get("BRIDGE_DSN", "")
    if not dsn:
        raise SystemExit("Set BRIDGE_DSN to the bridge database address (see the usage in this file's docstring).")
    lid_to_pn, names = load_bridge_maps(dsn)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        out = run(db, tenant.id, lid_to_pn, names)
        print("APPLIED" if args.apply else "DRY RUN (nothing written; add --apply)")
        print(f"  bridge knows {len(lid_to_pn)} hidden-id numbers and {len(names)} contact names")
        for k, v in out.items():
            print(f"  {k.replace('_', ' '):26} {v}")
        if args.apply:
            db.commit()
        else:
            db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
