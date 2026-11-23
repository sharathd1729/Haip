"""Delete everything HAIP mirrored from ONE personal WhatsApp number (a test pairing, or a number taken off HAIP).

    docker compose -f docker-compose.prod.yml exec -T api python scripts/purge_personal_whatsapp_session.py \\
        --tenant-slug rathaa --phone +91XXXXXXXXXX            # dry run: counts only
    ... --apply                                                 # deletes; cannot be undone

What goes (only rows this number's session wrote; its id is on every mirrored message, channel_metadata.session_id):
  * people who exist ONLY because of this number (every chat of theirs is a personal-WhatsApp mirror written by this
    session; no calls, no bookings, no quote sent): erased with the DPDP erasure (dpdp_erasure_service.erase_guest:
    chats, messages, auto-created leads, identities, consents, stored files; an anonymised tombstone row stays for the
    audit trail). Someone the team sent a quote keeps the lead and quote; only the chats go;
  * for everyone else: just this number's messages (and their photos / voice notes in storage), and a mirrored chat that
    is left with no messages.
Unpair the number first (the script refuses while it is connected, or new messages would keep arriving). Prints counts,
never names, numbers or message text. One transaction; files are deleted only after it commits; audited
(personal_whatsapp.session_purged).
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.getcwd())


def run(db, tenant_slug: str, phone: str, apply: bool, allow_connected: bool = False) -> dict:
    from sqlalchemy import String, cast

    from app.core.audit import append_audit
    from app.core.database import set_tenant_context
    from app.models.agent_consult import AgentConsult
    from app.models.ai_draft_outcome import AIDraftOutcome
    from app.models.call import Call
    from app.models.conversation import Conversation, Message
    from app.models.inquiry import Inquiry
    from app.models.inquiry_360 import InquiryQuote
    from app.models.lead_attribution import LeadAttribution
    from app.models.property import Stay
    from app.models.task import Task
    from app.models.tenant import Tenant
    from app.models.whatsapp_personal_session import WhatsAppPersonalSession, WhatsAppPersonalSessionStatus
    from app.services import dpdp_erasure_service

    tenant = db.query(Tenant).filter_by(slug=tenant_slug).first()
    if tenant is None:
        raise SystemExit(f"No workspace with slug {tenant_slug!r}.")
    tid = tenant.id
    set_tenant_context(db, tid)
    session = db.query(WhatsAppPersonalSession).filter_by(tenant_id=tid, phone_number=phone).first()
    if session is None:
        raise SystemExit("No personal WhatsApp pairing with that number in this workspace.")
    status = getattr(session.status, "value", session.status)
    if status == WhatsAppPersonalSessionStatus.CONNECTED.value and not allow_connected:
        raise SystemExit("This number is still connected: unpair it in Settings > Personal WhatsApp first.")

    # Every message this session wrote (the LIKE narrows the scan; the exact check is in Python).
    msgs = [
        m
        for m in db.query(Message).filter(
            Message.tenant_id == tid, cast(Message.channel_metadata, String).like(f"%{session.id}%")
        )
        if isinstance(m.channel_metadata, dict)
        and m.channel_metadata.get("source") == "personal_bridge"
        and m.channel_metadata.get("session_id") == session.id
    ]
    mine = {m.id for m in msgs}
    conv_ids = {m.conversation_id for m in msgs}
    convs = (
        db.query(Conversation).filter(Conversation.tenant_id == tid, Conversation.id.in_(conv_ids)).all()
        if conv_ids
        else []
    )

    def only_this_number(guest_id: str) -> bool:
        for c in db.query(Conversation).filter_by(tenant_id=tid, guest_id=guest_id):
            if c.source != "personal_bridge":
                return False
            if any(mid not in mine for (mid,) in db.query(Message.id).filter_by(conversation_id=c.id)):
                return False
        has_call = db.query(Call.id).filter_by(tenant_id=tid, guest_id=guest_id).first() is not None
        has_stay = db.query(Stay.id).filter_by(tenant_id=tid, guest_id=guest_id).first() is not None
        return not (has_call or has_stay)

    def was_quoted(guest_id: str) -> bool:  # the team sent this person a quote: real sales work, keep the lead
        inq = db.query(Inquiry.id).filter_by(tenant_id=tid, guest_id=guest_id)
        return (
            db.query(InquiryQuote.id).filter(InquiryQuote.tenant_id == tid, InquiryQuote.inquiry_id.in_(inq)).first()
            is not None
        )

    guests = {c.guest_id for c in convs if c.guest_id}
    only = {g for g in guests if only_this_number(g)}
    quoted = {g for g in only if was_quoted(g)}
    erase = sorted(only - quoted)
    keep = guests - set(erase)
    report = {
        "session_status": status,
        "messages": len(msgs),
        "chats": len(convs),
        "people_erased": len(erase),
        "people_kept_other_messages_only": len(keep - quoted),
        "people_kept_quoted": len(quoted),
        "files": sum(1 for m in msgs if m.media_url),
        "applied": False,
    }
    if not apply:
        return report

    # Plain values first: the erasure deletes some of these rows, and their ORM objects can no longer be read after it.
    msg_rows = [(m.id, m.media_url) for m in msgs]
    conv_rows = [(c.id, c.source) for c in convs]
    files: list[str] = []
    for gid in erase:
        files += dpdp_erasure_service.erase_guest(db, tid, gid)["files"]
    left = [(mid, media) for mid, media in msg_rows if db.query(Message.id).filter_by(id=mid).first() is not None]
    left_ids = [mid for mid, _ in left]  # this number's messages in the chats of people who were kept
    files += [media for _, media in left if media]
    if left_ids:
        db.query(AIDraftOutcome).filter(AIDraftOutcome.draft_message_id.in_(left_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.replied_to_message_id.in_(left_ids)).update(
            {Message.replied_to_message_id: None}, synchronize_session=False
        )
        db.query(Message).filter(Message.id.in_(left_ids)).delete(synchronize_session=False)
    emptied = [
        cid
        for cid, source in conv_rows
        if source == "personal_bridge"
        and db.query(Conversation.id).filter_by(id=cid).first() is not None
        and db.query(Message.id).filter_by(conversation_id=cid).first() is None
    ]
    if emptied:
        db.query(AgentConsult).filter(AgentConsult.conversation_id.in_(emptied)).delete(synchronize_session=False)
        db.query(LeadAttribution).filter(LeadAttribution.conversation_id.in_(emptied)).delete(synchronize_session=False)
        db.query(Task).filter(Task.conversation_id.in_(emptied)).update(
            {Task.conversation_id: None}, synchronize_session=False
        )
        db.query(Conversation).filter(Conversation.id.in_(emptied)).delete(synchronize_session=False)
    report.update(applied=True, empty_chats_removed=len(emptied))
    append_audit(
        db,
        tenant_id=tid,
        action="personal_whatsapp.session_purged",
        actor_user_id=None,
        target_type="whatsapp_personal_session",
        target_id=session.id,
        payload={"actor": "script:purge_personal_whatsapp_session", **report},
    )
    db.commit()
    from app.services.media_storage import delete_tenant_objects

    report["files_deleted"] = delete_tenant_objects(tid, files)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--phone", required=True, help="the paired number exactly as Settings > Personal WhatsApp shows it")
    ap.add_argument("--apply", action="store_true", help="delete (default: dry run, counts only)")
    args = ap.parse_args()
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        report = run(db, args.tenant_slug, args.phone.replace(" ", ""), args.apply)
    finally:
        db.close()
    for k, v in report.items():
        print(f"{k}: {v}")
    if not report["applied"]:
        print("Dry run: nothing was deleted. Add --apply to delete (this cannot be undone).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
