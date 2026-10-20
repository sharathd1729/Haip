"""One-off: mark every lead that has a real booking as Sold, so reports and the lead journey count the sale.

What it does (a DRY RUN unless you pass --apply; nothing is written in a dry run):
  1. Every booking (Stay) of the tenant that is not cancelled (confirmed, checked in, checked out) and is linked to a lead
     (stays.inquiry_id): if that lead is not already in the tenant's Sold stage (is_closed_won), it is moved there through
     the audited stage paths (inquiry_service), so the stage log, ledger, audit trail, lead autopilot and lead journey all
     see the move. A lead that was marked LOST is first reopened (reopen_lost_inquiry, role "system", with a reason; its
     lost reason is cleared) and then moved to Sold.
  2. With --link-unlinked, a booking with NO lead is tied to its guest's lead when there is exactly ONE candidate: the
     guest's only enquiry that no other live booking already uses. Then that lead is marked Sold as in step 1. Bookings
     with no candidate or with several are only listed; nothing is guessed.

Bookings of sample-data guests are skipped. Running it twice changes nothing the second time.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/mark_booked_leads_sold.py --tenant-slug rathaa
    docker compose -f docker-compose.prod.yml exec api python3 scripts/mark_booked_leads_sold.py --tenant-slug rathaa --link-unlinked
    docker compose -f docker-compose.prod.yml exec api python3 scripts/mark_booked_leads_sold.py --tenant-slug rathaa --link-unlinked --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.inquiry import Inquiry, InquiryStage  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.models.property import Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import inquiry_service  # noqa: E402

LIVE = ("confirmed", "checked_in", "checked_out")
REASON = "Has a confirmed booking (one-off fix: booked leads marked Sold)"


def _stages(db, tenant_id: str) -> tuple[PipelineStage, PipelineStage]:
    stages = db.query(PipelineStage).filter_by(tenant_id=tenant_id).order_by(PipelineStage.order).all()
    won = next((s for s in stages if s.is_closed_won), None)
    reopen_to = (next((s for s in stages if s.is_valid_lead_entry), None)
                 or next((s for s in stages if s.key == "active"), None)
                 or next((s for s in stages if not s.is_closed_won and not s.is_closed_lost), None))
    if won is None or reopen_to is None:
        raise SystemExit("This workspace has no Sold stage (is_closed_won) or no open stage to reopen into.")
    return won, reopen_to


def _candidate_lead(db, tenant_id: str, stay: Stay, used: set[str]):
    """The guest's only enquiry not already tied to another live booking, or None (no candidate / more than one)."""
    leads = [i for i in db.query(Inquiry).filter_by(tenant_id=tenant_id, guest_id=stay.guest_id).all() if i.id not in used]
    return leads[0] if len(leads) == 1 else None


def mark_sold(db, tenant_id: str, inquiry: Inquiry, won: PipelineStage, reopen_to: PipelineStage) -> str:
    """Move one lead to Sold. Returns "already" | "moved" | "reopened". Raises on a refused move."""
    if inquiry.stage_id == won.id:
        return "already"
    if inquiry.stage_id is None:
        inquiry.stage_id = inquiry_service._stage_id_for(db, tenant_id, inquiry.stage or InquiryStage.NEW)
        db.flush()
    current = db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=tenant_id).first()
    outcome = "moved"
    if current is not None and current.is_closed_lost:
        inquiry_service.reopen_lost_inquiry(db, tenant_id=tenant_id, inquiry_id=inquiry.id, new_stage_id=reopen_to.id,
                                            actor_user_id=None, actor_role="system", reason=REASON)
        outcome = "reopened"
    inquiry_service.update_stage_by_id(db, tenant_id=tenant_id, inquiry_id=inquiry.id, new_stage_id=won.id,
                                       actor_user_id=None, actor_role="system", reason=REASON)
    return outcome


def run(db, tenant_id: str, link_unlinked: bool = False) -> dict:
    """Do everything in the session and report it. The caller commits (--apply) or rolls back (dry run)."""
    won, reopen_to = _stages(db, tenant_id)
    sample = db.query(Guest.id).filter(Guest.tenant_id == tenant_id, Guest.is_sample.is_(True))
    stays = (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.status.in_(LIVE), Stay.guest_id.notin_(sample))
             .order_by(Stay.check_in).all())
    out = {"bookings": len(stays), "already_sold": 0, "moved": 0, "reopened_from_lost": 0, "linked": 0,
           "unlinked_no_candidate": 0, "unlinked_left": 0, "refused": []}
    used = {s.inquiry_id for s in stays if s.inquiry_id}
    done: set[str] = set()
    for stay in stays:
        inquiry = None
        if stay.inquiry_id:
            inquiry = db.query(Inquiry).filter_by(id=stay.inquiry_id, tenant_id=tenant_id).first()
        elif not link_unlinked:
            out["unlinked_left"] += 1
            continue
        else:
            inquiry = _candidate_lead(db, tenant_id, stay, used)
            if inquiry is None:
                out["unlinked_no_candidate"] += 1
                continue
            stay.inquiry_id = inquiry.id
            used.add(inquiry.id)
            append_audit(db, tenant_id=tenant_id, actor_user_id=None, action="booking.lead_linked", target_type="booking",
                         target_id=stay.id, payload={"inquiry_id": inquiry.id, "reason": REASON})
            out["linked"] += 1
        if inquiry is None or inquiry.id in done:
            continue
        done.add(inquiry.id)
        try:
            with db.begin_nested():
                result = mark_sold(db, tenant_id, inquiry, won, reopen_to)
        except (inquiry_service.InvalidStageTransition, ValueError) as exc:
            out["refused"].append({"booking": stay.id, "lead": inquiry.id, "reason": str(getattr(exc, "detail", exc))[:200]})
            continue
        key = {"already": "already_sold", "moved": "moved", "reopened": "reopened_from_lost"}[result]
        out[key] += 1
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--link-unlinked", action="store_true", help="tie bookings with no lead to the guest's only lead")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        set_tenant_context(db, tenant.id)
        out = run(db, tenant.id, link_unlinked=args.link_unlinked)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print("APPLIED" if args.apply else "DRY RUN (nothing written; add --apply)")
        print(f"Live bookings: {out['bookings']}")
        print(f"  lead already Sold:          {out['already_sold']}")
        print(f"  lead moved to Sold:         {out['moved']}")
        print(f"  lead reopened from Lost:    {out['reopened_from_lost']}  (then moved to Sold)")
        if args.link_unlinked:
            print(f"  booking tied to its lead:   {out['linked']}")
            print(f"  booking with no clear lead: {out['unlinked_no_candidate']}  (left as is)")
        else:
            print(f"  booking with no lead:       {out['unlinked_left']}  (run with --link-unlinked to tie them)")
        for r in out["refused"]:
            print(f"  NOT moved: booking {r['booking']} lead {r['lead']}: {r['reason']}")
        if args.apply:
            print("Next: the lead journey picks up the Sold outcomes within 5 minutes (or run backfill_lead_journeys.py --apply).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
