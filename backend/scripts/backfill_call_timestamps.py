"""Repair call times that Vobiz stored in the wrong shape.

Until Nov 2026 the Vobiz webhooks stored `calls.ended_at` as raw epoch milliseconds ("1793595257042") and left
`calls.started_at` empty (Vobiz's answer callback sends no StartTime). Every report, the QA card, the owner digest,
callback recovery and retention compare `started_at` against an ISO date, so those calls silently dropped out.
New calls are stored as ISO-8601 UTC (webhooks_vobiz._iso_utc); this fixes the old rows.

What it changes (a DRY RUN unless you pass --apply; nothing is written in a dry run), per tenant:
  * a numeric `ended_at` / `started_at` (epoch ms or seconds) -> ISO-8601 UTC;
  * an empty `started_at` -> `ended_at` minus `duration_seconds`, else the row's `created_at`.
Rows already in another readable format are left alone. Only counts are printed: no phone numbers, no call ids.

Usage (inside the API container):
    python3 scripts/backfill_call_timestamps.py [--tenant-slug rathaa]
    ... same command with --apply to write.
"""

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import or_  # noqa: E402

from app.api.v1.endpoints.webhooks_vobiz import _iso_utc  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.call import Call  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402


def _numeric(value) -> bool:
    raw = str(value or "").strip()
    return bool(raw) and raw.replace(".", "", 1).isdigit()


def run(db, tenant_id: str, *, apply: bool = False) -> dict:
    out = {
        "calls_checked": 0,
        "ended_at_converted": 0,
        "started_at_converted": 0,
        "started_from_end_minus_duration": 0,
        "started_from_created_at": 0,
        "unfixable": 0,
    }
    rows = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id,
            or_(
                Call.started_at.is_(None),
                Call.started_at == "",
                ~Call.started_at.contains("-"),
                ~Call.ended_at.contains("-"),
            ),
        )
        .all()
    )
    for call in rows:
        out["calls_checked"] += 1
        ended, started = call.ended_at, call.started_at
        if _numeric(ended):
            ended = _iso_utc(ended)
            out["ended_at_converted"] += 1
        if _numeric(started):
            started = _iso_utc(started)
            out["started_at_converted"] += 1
        if not (started or "").strip():
            if ended and "-" in ended:
                try:
                    started = (
                        datetime.fromisoformat(ended.replace("Z", "+00:00"))
                        - timedelta(seconds=call.duration_seconds or 0)
                    ).isoformat()
                    out["started_from_end_minus_duration"] += 1
                except ValueError:
                    started = None
            if not started and call.created_at:
                created = call.created_at if call.created_at.tzinfo else call.created_at.replace(tzinfo=UTC)
                started = created.astimezone(UTC).isoformat()
                out["started_from_created_at"] += 1
            if not started:
                out["unfixable"] += 1
                continue
        if apply:
            call.ended_at, call.started_at = ended, started
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", help="one workspace (default: every workspace)")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        q = db.query(Tenant.id, Tenant.slug)
        if args.tenant_slug:
            q = q.filter(Tenant.slug == args.tenant_slug)
        tenants = q.order_by(Tenant.slug).all()
        if not tenants:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        print("APPLYING" if args.apply else "DRY RUN (nothing written; add --apply)")
        for tid, slug in tenants:
            set_tenant_context(db, tid)  # one transaction per tenant (RLS)
            out = run(db, tid, apply=args.apply)
            if args.apply:
                db.commit()
            else:
                db.rollback()
            if out["calls_checked"]:
                print(f"{slug}: " + ", ".join(f"{k}={v}" for k, v in out.items()))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
