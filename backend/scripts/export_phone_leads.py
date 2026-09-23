"""Export leads who gave us a phone number, split by enquiry month.

Two .xlsx files: one for enquiries made in a chosen month (default September
2026) and one for everything before it, so the older backlog can be worked
separately from the current month.

Only leads with a real phone number are included -- an Instagram handle with
no number can't be called, and that is what these lists are for.

Read-only: it opens the database, reads, and writes two files. Nothing is
updated, nothing is sent.

    # on the VPS
    docker compose -f docker-compose.prod.yml exec api \
        python scripts/export_phone_leads.py --month 2026-09 --out /tmp

    docker compose -f docker-compose.prod.yml cp api:/tmp/leads_september_2026.xlsx .
    docker compose -f docker-compose.prod.yml cp api:/tmp/leads_before_september_2026.xlsx .

Options:
    --month YYYY-MM   the "current" month to split on (default 2026-09)
    --tenant SLUG     one workspace (default: every workspace)
    --out DIR         where to write (default: current directory)
    --include-unqualified   also list leads triaged as unqualified/spam
"""
from __future__ import annotations

import argparse
import os
import sys
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import joinedload

from app.core.database import SessionLocal
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User

IST = timezone(timedelta(hours=5, minutes=30))

COLUMNS = [
    ("Enquiry date (IST)", 18),
    ("Name", 22),
    ("Instagram", 18),
    ("Phone", 16),
    ("Email", 24),
    ("Came in via", 14),
    ("Stage", 18),
    ("Owner", 14),
    ("Check-in", 12),
    ("Check-out", 12),
    ("Adults", 8),
    ("Children", 9),
    ("Budget", 12),
    ("Quoted", 12),
    ("Occasion", 14),
    ("Trip / route", 22),
    ("Property", 20),
    ("Guest city", 14),
    ("Asked for", 26),
    ("Special requests", 30),
    ("Last touch (IST)", 18),
    ("Remarks (AI summary)", 60),
    ("Suggested next step", 34),
]


def _ist(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt[:16].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M")


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    # Excel refuses anything over 32767 chars in one cell.
    return text[:2000]


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    year, mon = (int(p) for p in month.split("-"))
    first = date(year, mon, 1)
    last = date(year, mon, monthrange(year, mon)[1])
    start = datetime.combine(first, time.min, tzinfo=IST).astimezone(timezone.utc)
    end = datetime.combine(last, time.max, tzinfo=IST).astimezone(timezone.utc)
    return start, end


def _rows(db, tenant_ids: list[str], start, end, include_unqualified: bool) -> list[list]:
    q = (
        db.query(Inquiry)
        .options(joinedload(Inquiry.guest))
        .filter(Inquiry.tenant_id.in_(tenant_ids))
    )
    if start is not None:
        q = q.filter(Inquiry.created_at >= start)
    if end is not None:
        q = q.filter(Inquiry.created_at <= end)
    if not include_unqualified:
        q = q.filter(Inquiry.qualification_status != "unqualified")
    inquiries = q.order_by(Inquiry.created_at.desc()).all()
    if not inquiries:
        return []

    guest_ids = {i.guest_id for i in inquiries if i.guest_id}
    handles: dict[str, str] = {}
    for row in db.query(GuestIdentity).filter(
        GuestIdentity.guest_id.in_(guest_ids),
        GuestIdentity.identity_type.in_(("instagram_user_id", "instagram_username")),
    ):
        handles.setdefault(row.guest_id, row.identity_value)

    stages = {
        s.id: s.label
        for s in db.query(PipelineStage).filter(PipelineStage.tenant_id.in_(tenant_ids))
    }
    owners = {u.id: u.name for u in db.query(User).filter(User.tenant_id.in_(tenant_ids))}
    props = {p.id: p.name for p in db.query(Property).filter(Property.tenant_id.in_(tenant_ids))}

    rows = []
    for inq in inquiries:
        guest = inq.guest
        phone = (guest.phone if guest else "") or ""
        if not phone.strip():
            continue  # the whole point of these lists is a number to ring
        ai = inq.ai_analysis if isinstance(inq.ai_analysis, dict) else {}
        rows.append([
            _ist(inq.created_at),
            _clean(guest.name if guest else ""),
            _clean(handles.get(inq.guest_id, "")),
            _clean(phone),
            _clean(guest.email if guest else ""),
            _clean(inq.source.value if inq.source else ""),
            _clean(stages.get(inq.stage_id) or (inq.stage.value if inq.stage else "")),
            _clean(owners.get(inq.assigned_to, "")),
            _clean(inq.check_in),
            _clean(inq.check_out),
            inq.adults or "",
            inq.children or "",
            float(inq.budget) if inq.budget is not None else "",
            float(inq.quoted_amount) if inq.quoted_amount is not None else "",
            _clean(inq.occasion),
            _clean(inq.route_mentioned),
            _clean(props.get(inq.property_id, "")),
            _clean(guest.city if guest else ""),
            _clean(ai.get("intent") or inq.intent_tag),
            _clean(inq.special_requests),
            _ist(inq.last_touch_at if hasattr(inq, "last_touch_at") else None) or _ist(inq.updated_at),
            _clean(inq.ai_summary),
            _clean(inq.ai_next_action or ai.get("next_action")),
        ])
    return rows


def _write(path: str, title: str, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]

    header_fill = PatternFill("solid", fgColor="0F766E")
    header_font = Font(bold=True, color="FFFFFF")
    for col, (name, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(len(rows) + 1, 2)}"

    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            if COLUMNS[c - 1][0] in ("Remarks (AI summary)", "Special requests", "Suggested next step"):
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(path)
    print(f"  {path}  ({len(rows)} leads)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", default="2026-09", help="YYYY-MM to split on (default 2026-09)")
    ap.add_argument("--tenant", default=None, help="workspace slug (default: all)")
    ap.add_argument("--out", default=".", help="output directory")
    ap.add_argument("--include-unqualified", action="store_true")
    args = ap.parse_args()

    start, end = _month_bounds(args.month)
    label = datetime.strptime(args.month, "%Y-%m").strftime("%B %Y")
    slug = datetime.strptime(args.month, "%Y-%m").strftime("%B_%Y").lower()

    db = SessionLocal()
    try:
        tq = db.query(Tenant)
        if args.tenant:
            tq = tq.filter(Tenant.slug == args.tenant)
        tenants = tq.all()
        if not tenants:
            print(f"No workspace matched {args.tenant!r}")
            return 1
        tenant_ids = [t.id for t in tenants]
        print("Workspaces:", ", ".join(t.slug for t in tenants))

        in_month = _rows(db, tenant_ids, start, end, args.include_unqualified)
        before = _rows(db, tenant_ids, None, start - timedelta(microseconds=1), args.include_unqualified)
    finally:
        db.close()

    os.makedirs(args.out, exist_ok=True)
    print("Written:")
    _write(os.path.join(args.out, f"leads_{slug}.xlsx"), label, in_month)
    _write(os.path.join(args.out, f"leads_before_{slug}.xlsx"), f"Before {label}", before)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
