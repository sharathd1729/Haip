"""
Read-only: list leads whose pipeline stage disagrees with the facts HAIP holds.

  1. lost_but_guest_wrote  -- in Lost, yet the guest messaged us AFTER it was closed (the lead_reopen rule now reopens these;
                              older ones from before that rule still sit in Lost)
  2. booked_not_sold       -- in Lost or an open stage while a live booking (not cancelled) is linked to it, or made for the
                              guest after the lead started with no lead linked (should be Sold)
  3. active_date_passed    -- in the "qualified" stage (Active) with a travel date in the past and no live booking

Nothing is written: no stage moves, no audit rows. Phones are printed masked (last 4 digits only). Fixes go through the
normal audited paths: scripts/reopen_lost_leads.py (1), scripts/mark_booked_leads_sold.py (2), the lead page (3).

  cd backend
  python scripts/diagnose_lead_stages.py --tenant-slug rathaa
  python scripts/diagnose_lead_stages.py --tenant-slug rathaa --limit 200
"""
import argparse
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func  # noqa: E402

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.conversation import Conversation, Message, MessageDirection  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.inquiry_360 import InquiryStageLog  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.models.property import Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.lead_autopilot_rules import StageMap  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
# Mirrored history and imported chat exports are not the guest writing again (lead_reopen uses live messages only).
_NOT_LIVE_KINDS = ("bridge_history", "chat_export")


def mask(phone) -> str:
    d = re.sub(r"\D", "", phone or "")
    return f"******{d[-4:]}" if len(d) >= 4 else "(no phone)"


def _aware(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def find(db, tenant_id: str, today: date) -> dict:
    """The three lists, each row a dict. Pure reads."""
    stages = StageMap.load(db, tenant_id)
    by_id = {s.id: s for s in stages.stages}
    lost_ids = {s.id for s in stages.stages if s.is_closed_lost}
    won_ids = {s.id for s in stages.stages if s.is_closed_won}
    leads = db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.stage_id.isnot(None)).all()
    guests = {g.id: g for g in db.query(Guest).filter(Guest.tenant_id == tenant_id,
                                                      Guest.id.in_({i.guest_id for i in leads if i.guest_id})).all()}
    stays = db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.status != "cancelled").all()
    stays_by_lead, unlinked_by_guest = {}, {}
    for s in stays:
        if s.inquiry_id:
            stays_by_lead.setdefault(s.inquiry_id, []).append(s)
        else:
            unlinked_by_guest.setdefault(s.guest_id, []).append(s)

    def row(inq, **extra):
        g = guests.get(inq.guest_id)
        st = by_id.get(inq.stage_id)
        return {"inquiry_id": inq.id, "guest": (g.name if g else None) or "(no name)", "phone": mask(g.phone if g else None),
                "stage": st.label if st else "?", **extra}

    out = {"lost_but_guest_wrote": [], "booked_not_sold": [], "active_date_passed": []}

    # 1. Lost, and the guest wrote after the close
    lost = [i for i in leads if i.stage_id in lost_ids]
    for inq in lost:
        st = by_id[inq.stage_id]
        log = (db.query(InquiryStageLog).filter_by(tenant_id=tenant_id, inquiry_id=inq.id, to_stage=st.key)
               .order_by(InquiryStageLog.changed_at.desc()).first())
        closed_at = _aware(log.changed_at if log else inq.current_stage_entered_at)
        if closed_at is None or not inq.guest_id:
            continue
        q = (db.query(func.count(Message.id), func.max(Message.created_at))
             .join(Conversation, Conversation.id == Message.conversation_id)
             .filter(Message.tenant_id == tenant_id, Conversation.guest_id == inq.guest_id,
                     Message.direction == MessageDirection.INBOUND, Message.is_internal.is_(False), Message.created_at > closed_at,
                     (Message.sender_kind.is_(None)) | (Message.sender_kind.notin_(_NOT_LIVE_KINDS))))
        n, last = q.one()
        if n:
            out["lost_but_guest_wrote"].append(row(
                inq, closed_by="system" if log and log.changed_by == "system" else "person",
                closed_at=closed_at.astimezone(IST).strftime("%d %b %Y"), messages_after=n,
                last_message=_aware(last).astimezone(IST).strftime("%d %b %Y %H:%M") if last else None))

    # 2. Not Sold, but a live booking belongs to it
    for inq in leads:
        if inq.stage_id in won_ids:
            continue
        linked = stays_by_lead.get(inq.id, [])
        loose = [s for s in unlinked_by_guest.get(inq.guest_id, [])
                 if _aware(s.created_at) and _aware(inq.created_at) and _aware(s.created_at) >= _aware(inq.created_at)]
        if linked or loose:
            s = (linked or loose)[0]
            out["booked_not_sold"].append(row(inq, booking=f"{s.check_in} to {s.check_out}", linked=bool(linked)))

    # 3. Active with a travel date gone by and no booking
    if stages.qualified is not None:
        for inq in leads:
            if inq.stage_id != stages.qualified.id:
                continue
            ci = _parse_date(inq.check_in)
            if ci is None or ci >= today or stays_by_lead.get(inq.id) or unlinked_by_guest.get(inq.guest_id):
                continue
            out["active_date_passed"].append(row(inq, check_in=ci.isoformat()))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--limit", type=int, default=50, help="Rows printed per list (counts are always complete)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No workspace with slug '{args.tenant_slug}'.")
            return 1
        set_tenant_context(db, tenant.id)
        found = find(db, tenant.id, datetime.now(IST).date())
        print(f"Workspace: {tenant.name}   (read-only; nothing was changed)")
        titles = {"lost_but_guest_wrote": "Lost, but the guest wrote after it was closed",
                  "booked_not_sold": "Has a live booking, but not Sold",
                  "active_date_passed": "Active, travel date passed, no booking"}
        for key, rows in found.items():
            print(f"\n== {titles[key]}: {len(rows)}")
            if key == "lost_but_guest_wrote" and rows:
                print("   closed by: " + ", ".join(f"{k} {v}" for k, v in Counter(r["closed_by"] for r in rows).items()))
            for r in rows[:args.limit]:
                print("   " + "  ".join(f"{k}={v}" for k, v in r.items()))
            if len(rows) > args.limit:
                print(f"   ... {len(rows) - args.limit} more (use --limit)")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
