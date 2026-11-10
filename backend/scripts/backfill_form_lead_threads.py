"""
One-off: lead-form leads imported before form leads got an Inbox thread have none. Give each its "Facebook" thread
(the form's answers as a staff note), exactly as a new form lead gets now, and fill the lead's empty Guests / Dates /
Budget / Occasion from the form's answers (never overwriting what is already set). A value the first version of this
reader got wrong (10 Nov: "1.5 lakh" read as 5, the year in "28th Dec 2027" ignored, "< 250" guests dropped) is corrected
when it is still exactly what that version wrote.

    python scripts/backfill_form_lead_threads.py --tenant-slug jade-hospitainment          # dry run
    python scripts/backfill_form_lead_threads.py --tenant-slug jade-hospitainment --apply

A person who already has a thread on any channel is skipped. Prints counts only. Safe to re-run.
"""

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.meta_form_lead import MetaFormLead  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.meta_lead_forms_service import apply_trip_facts, open_thread, trip_facts  # noqa: E402


def _v1_trip_facts(answers: dict, filled: date) -> dict:
    """What the first version (10 Nov, PR #167) wrote, so only those values are corrected. Kept as it was, bugs included."""
    num = re.compile(r"\d[\d,]*")
    out: dict = {}
    for question, raw in (answers or {}).items():
        q, text = question.lower(), str(raw).replace("_", " ")
        nums = [int(n.replace(",", "")) for n in num.findall(text) if n.replace(",", "")]
        if not nums:
            continue
        if "budget" in q or "price" in q or "spend" in q:
            out.setdefault("budget", float(max(nums)))
        elif any(w in q for w in ("guest", "people", "pax", "party", "persons", "members", "how many")):
            small = [n for n in nums if n <= 200]
            if small:
                out.setdefault("adults", max(small))
        elif "date" in q or "when" in q:
            from app.services.ical_event_details import _month
            from app.services.meta_lead_forms_service import _numbers

            month = next((m for w in re.findall(r"[a-z]{3,9}", text, re.I) if (m := _month(w))), None)
            days = []
            for day in [n for n in _numbers(text) if 1 <= n <= 31][:2]:
                tries = (
                    [(filled.year, month), (filled.year + 1, month)]
                    if month
                    else [
                        (filled.year + (filled.month + i - 1) // 12, (filled.month + i - 1) % 12 + 1) for i in range(13)
                    ]
                )
                for y, mon in tries:
                    try:
                        d = date(y, mon, day)
                    except ValueError:
                        continue
                    if d >= filled:
                        days.append(d)
                        break
            days = sorted(set(days))
            if days:
                out.setdefault("check_in", days[0].isoformat())
                out.setdefault("check_out", (days[-1] if len(days) > 1 else days[0] + timedelta(days=1)).isoformat())
    return out


def _would_change(inq, answers: dict, filled: date, old: dict) -> bool:
    for field, value in trip_facts(answers, filled).items():
        current = getattr(inq, field)
        current = float(current) if field == "budget" and current is not None else current
        if current in (None, "") or (field in old and old[field] == current and current != value):
            return True
    return False


def backfill(db, tenant_id: str, apply: bool) -> dict:
    counts = {"form_leads": 0, "threads_made": 0, "already_have_a_thread": 0, "leads_given_trip_facts": 0}
    rows = (
        db.query(MetaFormLead)
        .filter(
            MetaFormLead.tenant_id == tenant_id, MetaFormLead.guest_id.isnot(None), MetaFormLead.inquiry_id.isnot(None)
        )
        .order_by(MetaFormLead.lead_created_at.asc())
        .all()
    )
    seen: set[str] = set()
    for rec in rows:
        counts["form_leads"] += 1
        inq = db.query(Inquiry).filter_by(id=rec.inquiry_id, tenant_id=tenant_id).first()
        answers = (((inq.custom_fields or {}).get("lead_form") or {}).get("answers") or {}) if inq else {}
        filled = (rec.lead_created_at or rec.created_at).date()
        old = _v1_trip_facts(answers, filled)
        if inq is not None and _would_change(inq, answers, filled, old):
            counts["leads_given_trip_facts"] += 1
            if apply:
                apply_trip_facts(inq, answers, filled, replace=old)
        has = (
            rec.guest_id in seen
            or db.query(Conversation.id).filter_by(tenant_id=tenant_id, guest_id=rec.guest_id).first()
        )
        if has:
            counts["already_have_a_thread"] += 1
            continue
        seen.add(rec.guest_id)
        counts["threads_made"] += 1
        if apply:
            inquiry = db.query(Inquiry).filter_by(id=rec.inquiry_id, tenant_id=tenant_id).first()
            if inquiry is not None:
                open_thread(db, tenant_id, rec, inquiry)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=a.tenant_slug).one_or_none()
        if not tenant:
            print("ERROR: unknown tenant slug")
            return 2
        set_tenant_context(db, tenant.id)
        counts = backfill(db, tenant.id, a.apply)
        if a.apply:
            db.commit()
        print(("APPLIED" if a.apply else "DRY RUN (add --apply)") + f": {counts}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
