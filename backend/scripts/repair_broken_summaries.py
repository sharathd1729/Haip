"""Find leads whose stored AI summary is a raw field dump, not prose, and (with --apply) queue a fresh summary for each.

The bug (Oct 2026): when the model answered with a markdown rendering of the JSON fields ("Requirements:" then
"`requirements`: [...]") or a cut-off fragment instead of the JSON object, generate_ai_summary stored that text verbatim
as inquiries.ai_summary. The task now rejects such replies (generate_ai_summary.summary_rejection_reason) and keeps the
previous summary; this script finds the summaries already stored that fail the SAME check.

A DRY RUN unless you pass --apply: it prints short inquiry ids and the rejection reason only (no guest names, numbers or
summary text). --apply re-queues generate_ai_summary (Celery, queue as routed) for each lead; it writes nothing itself.
The stored summary is replaced only when the new run produces a clean one.

Usage (inside the API container, against production):
    docker exec -i haip_api python3 scripts/repair_broken_summaries.py --tenant-slug rathaa
    docker exec -i haip_api python3 scripts/repair_broken_summaries.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.workers.tasks.generate_ai_summary import summary_rejection_reason  # noqa: E402


def broken_summaries(db, tenant_id: str) -> list[tuple[str, str]]:
    """[(inquiry_id, reason)] for this tenant's inquiries whose stored ai_summary fails the task's own prose check."""
    rows = (
        db.query(Inquiry.id, Inquiry.ai_summary)
        .filter(Inquiry.tenant_id == tenant_id, Inquiry.ai_summary.isnot(None), Inquiry.ai_summary != "")
        .all()
    )
    out = []
    for inquiry_id, text in rows:
        reason = summary_rejection_reason(text)
        if reason:
            out.append((inquiry_id, reason))
    return out


def requeue(found: list[tuple[str, str]], tenant_id: str) -> tuple[int, list[tuple[str, str]]]:
    """Queue generate_ai_summary for each lead. Returns (queued, [(inquiry_id, error)])."""
    from app.workers.tasks.generate_ai_summary import generate_ai_summary

    queued, failed = 0, []
    for inquiry_id, _ in found:
        try:
            generate_ai_summary.delay(inquiry_id=inquiry_id, tenant_id=tenant_id)
            queued += 1
        except Exception as exc:  # noqa: BLE001 -- report and carry on with the others
            failed.append((inquiry_id, type(exc).__name__))
    return queued, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tenant-slug", required=True, help="the workspace to check")
    parser.add_argument("--apply", action="store_true", help="queue a fresh summary for each (default: report only)")
    parser.add_argument("--show", type=int, default=50, help="how many ids to list")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        set_tenant_context(db, tenant.id)
        found = broken_summaries(db, tenant.id)
        print("APPLY" if args.apply else "DRY RUN (nothing queued; add --apply to re-queue)")
        print(f"{tenant.slug}: {len(found)} lead(s) with a broken AI summary")
        for reason, n in Counter(r for _, r in found).most_common():
            print(f"  {reason}: {n}")
        for inquiry_id, reason in found[: args.show]:
            print(f"  {inquiry_id[:8]}  {reason}")
        if args.apply and found:
            queued, failed = requeue(found, tenant.id)
            print(f"queued {queued}, failed {len(failed)}")
            for inquiry_id, err in failed:
                print(f"  failed {inquiry_id[:8]}: {err}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
