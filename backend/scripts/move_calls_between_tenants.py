"""
Move one IVR number's calls from one tenant to another (e.g. Jade's Mcube number whose calls
landed in Ratha's workspace, 23 Jul - 5 Aug 2026).

    python scripts/move_calls_between_tenants.py --from-slug rathaa --to-slug jade-hospitainment \
        --provider mcube --to-number +918970663366            # dry run (default): counts only
    ... --apply                                               # writes

Rules
- Calls: every call in the source tenant with that provider (and landing number, when --to-number is given) moves.
- identity_service commits as it resolves guests, so an --apply interrupted midway is not rolled back fully;
  re-running --apply finishes it (calls already pointing at a target guest are simply moved).
- Guests: a guest whose ONLY source-tenant activity is these calls (no other call, no WhatsApp/
  Instagram/webchat/email conversation, no stay) moves with everything that references it, plus
  its inquiries and conversations. Otherwise the guest STAYS (it is the source tenant's guest too);
  its moved calls are attached to a guest resolved in the target tenant by phone through
  identity_service (the only place for GID resolution), with an open inquiry there. A guest whose
  identity (phone etc.) already exists in the target tenant is treated the same way, so the
  target never gets a duplicate identity.
- Every table with a tenant_id is found from the SQLAlchemy metadata: rows whose id is a moved
  call/guest/inquiry/conversation, or whose call_id/guest_id/inquiry_id/conversation_id points at
  one, get the target tenant_id. audit_events is never rewritten (its hash chain is per tenant).
- Bookings/stays never move (a guest with a stay stays). Recording files stay where they are:
  playback presigns the stored recording_s3_key, whatever tenant prefix it has.
- Output is counts only, never phone numbers or names. Re-running after --apply moves nothing.
- Audit: one transaction per tenant (CLAUDE.md): the move + the target's audit row commit together,
  then the source's audit row. If the second commit fails, re-run with --apply: the move finds
  nothing and only the source audit row is written.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, or_, update, select  # noqa: E402

import app.models  # noqa: E402,F401  (registers every table on Base.metadata)
from app.core.audit import append_audit  # noqa: E402
from app.core.database import Base, SessionLocal  # noqa: E402
from app.models.call import Call  # noqa: E402
from app.models.conversation import ChannelType, Conversation  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.guest_identity import GuestIdentity  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.property import Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402

REFS = {"call_id": "calls", "guest_id": "guests", "inquiry_id": "inquiries", "conversation_id": "conversations"}
NEVER_REWRITE = {"audit_events"}
_ROUTINE_CHANNELS = (ChannelType.VOICE, ChannelType.INTERNAL)


def _guest_moves(db, src: str, dst: str, guest_id: str, call_ids: set) -> bool:
    other_calls = db.query(func.count(Call.id)).filter(
        Call.tenant_id == src, Call.guest_id == guest_id, Call.id.notin_(call_ids)).scalar()
    chats = db.query(func.count(Conversation.id)).filter(
        Conversation.tenant_id == src, Conversation.guest_id == guest_id,
        Conversation.channel.notin_(_ROUTINE_CHANNELS)).scalar()
    stays = db.query(func.count(Stay.id)).filter(Stay.tenant_id == src, Stay.guest_id == guest_id).scalar()
    if other_calls or chats or stays:
        return False
    idents = db.query(GuestIdentity.identity_type, GuestIdentity.identity_value).filter(
        GuestIdentity.tenant_id == src, GuestIdentity.guest_id == guest_id).all()
    clash = any(db.query(GuestIdentity.id).filter_by(tenant_id=dst, identity_type=t, identity_value=v).first()
                for t, v in idents)
    return not clash


def plan_and_move(db, *, src: str, dst: str, provider: str, to_number: str, apply: bool) -> dict:
    q = db.query(Call).filter(Call.tenant_id == src, Call.ivr_provider == provider)
    calls = (q.filter(Call.to_number == to_number) if to_number else q).all()
    call_ids = {c.id for c in calls}
    report = {"calls": len(calls), "guests_moved": 0, "guests_kept": 0, "calls_reattached": 0, "tables": {}}
    if not calls:
        return report

    moving_guests, kept = set(), set()
    for gid in {c.guest_id for c in calls if c.guest_id}:
        (moving_guests if _guest_moves(db, src, dst, gid, call_ids) else kept).add(gid)
    report["guests_moved"], report["guests_kept"] = len(moving_guests), len(kept)

    if apply and kept:
        from app.workers.tasks.call_ingest import _dedup_guest, _find_or_create_inquiry
        for c in calls:
            if c.guest_id in kept and c.from_number:
                guest = _dedup_guest(db, dst, c.from_number)
                c.guest_id, c.inquiry_id = guest.id, _find_or_create_inquiry(db, dst, guest).id
                report["calls_reattached"] += 1
        db.flush()
    elif kept:
        report["calls_reattached"] = sum(1 for c in calls if c.guest_id in kept and c.from_number)

    moved = {
        "calls": call_ids,
        "guests": moving_guests,
        "inquiries": {i for (i,) in db.query(Inquiry.id).filter(
            Inquiry.tenant_id == src, Inquiry.guest_id.in_(moving_guests))} if moving_guests else set(),
        "conversations": {v for (v,) in db.query(Conversation.id).filter(
            Conversation.tenant_id == src, Conversation.guest_id.in_(moving_guests))} if moving_guests else set(),
    }

    for table in list(Base.metadata.tables.values()):   # not sorted_tables: that resolves every FK
        if "tenant_id" not in table.c or table.name in NEVER_REWRITE:
            continue
        conds = [table.c.id.in_(moved[table.name])] if table.name in moved and moved[table.name] and "id" in table.c else []
        conds += [table.c[col].in_(moved[kind]) for col, kind in REFS.items() if col in table.c and moved[kind]]
        if not conds:
            continue
        where = (table.c.tenant_id == src, or_(*conds))
        n = db.execute(select(func.count()).select_from(table).where(*where)).scalar()
        if n:
            report["tables"][table.name] = n
            if apply:
                db.execute(update(table).where(*where).values(tenant_id=dst))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from-slug", required=True)
    ap.add_argument("--to-slug", required=True)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--to-number", default="", help="landing/DID number, E.164; omit to move every call of the provider")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    db = SessionLocal()
    try:
        src = db.query(Tenant).filter_by(slug=a.from_slug).one_or_none()
        dst = db.query(Tenant).filter_by(slug=a.to_slug).one_or_none()
        if not src or not dst or src.id == dst.id:
            print("ERROR: both tenant slugs must exist and differ")
            return 2
        report = plan_and_move(db, src=src.id, dst=dst.id, provider=a.provider, to_number=a.to_number, apply=a.apply)
        set_provider = dst.ivr_provider != a.provider
        print("APPLYING" if a.apply else "DRY RUN (nothing written; add --apply)")
        print(f"calls={report['calls']} guests_moved={report['guests_moved']} guests_kept_in_source="
              f"{report['guests_kept']} calls_reattached={report['calls_reattached']}")
        for name, n in sorted(report["tables"].items()):
            print(f"  {name}: {n}")
        if set_provider:
            print(f"  {a.to_slug}.ivr_provider: {dst.ivr_provider!r} -> {a.provider!r}")
        if not a.apply:
            db.rollback()
            return 0
        if set_provider:
            dst.ivr_provider = a.provider
        payload = {"from": a.from_slug, "to": a.to_slug, "provider": a.provider, **{k: v for k, v in report.items() if k != "tables"}}
        if report["calls"]:
            append_audit(db, tenant_id=dst.id, action="calls.moved_in", target_type="tenant", target_id=src.id, payload=payload)
        db.commit()
        if report["calls"]:
            append_audit(db, tenant_id=src.id, action="calls.moved_out", target_type="tenant", target_id=dst.id, payload=payload)
            db.commit()
        print("done")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
