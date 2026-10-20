"""One-off: fill the lead journey (lead_journeys) for enquiries that came in before lead workflows existed.

What it does (a DRY RUN unless you pass --apply; nothing is written in a dry run): for every enquiry of the tenant received
in the last --days days (default 180), it runs the same refresh the 5-minute sweep runs (lead_journey_tracker.refresh):
received, assigned, first call attempt, first connected call, first human contact and its channel, proposal shared, and
the outcome from the stage. Milestones are written once, so running it twice changes nothing the second time.

What it cannot rebuild: "seen" (lead views) and "team notified" were never recorded before lead workflows; those stay empty
for older leads.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/backfill_lead_journeys.py --tenant-slug rathaa
    docker compose -f docker-compose.prod.yml exec api python3 scripts/backfill_lead_journeys.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.lead_workflow import LeadJourney  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import lead_journey_tracker as journey  # noqa: E402

BATCH = 100


def run(db, tenant_id: str, days: int) -> dict:
    """Refresh every enquiry received in the window. The caller commits (--apply) or rolls back (dry run)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    ids = [i for (i,) in db.query(Inquiry.id).filter(Inquiry.tenant_id == tenant_id, Inquiry.created_at >= since)
           .order_by(Inquiry.created_at).all()]
    before = db.query(LeadJourney.id).filter(LeadJourney.tenant_id == tenant_id).count()
    filled = 0
    for start in range(0, len(ids), BATCH):
        batch = db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.id.in_(ids[start:start + BATCH])).all()
        filled += journey.refresh(db, tenant_id, batch)
        db.flush()
    after = db.query(LeadJourney.id).filter(LeadJourney.tenant_id == tenant_id).count()
    outcomes: dict[str, int] = {}
    for (o,) in db.query(LeadJourney.outcome).filter(LeadJourney.tenant_id == tenant_id).all():
        outcomes[o] = outcomes.get(o, 0) + 1
    return {"enquiries": len(ids), "journeys_created": after - before, "milestones_filled": filled, "outcomes": outcomes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args()
    if not 1 <= args.days <= 1000:
        raise SystemExit("--days must be between 1 and 1000")
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        set_tenant_context(db, tenant.id)
        out = run(db, tenant.id, args.days)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        mode = "APPLIED" if args.apply else "DRY RUN (nothing written; add --apply)"
        print(f"{mode}: {out['enquiries']} enquiries in the last {args.days} days, "
              f"{out['journeys_created']} journeys created, {out['milestones_filled']} milestones filled")
        print("Outcomes:", ", ".join(f"{k} {v}" for k, v in sorted(out["outcomes"].items())) or "none")
    finally:
        db.close()


if __name__ == "__main__":
    main()
