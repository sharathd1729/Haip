"""Stay Account Report PDF (villa pack): the caravan Trip Account Report's shape without the kilometre section, drawn by the
same code (ops_trip_report.render). Sections: 1 guest & stay, 2 package & payment, 3 revised amount payable + deposit,
4 expenses, 5 net cash, 6 GST-adjusted revenue, 7 final position. Every number from ops_money.account and the booking ledger.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.tenant_tz import get_tz
from app.models.ops_files import OpsFile
from app.models.property import Property
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.services import ops_money as money
from app.services import ops_stay_service as stays
from app.services.invoice_pdf import inr_text
from app.services.ops_trip_report import EXPENSE_LINES, _hhmm, _mask, _q, _when


def build(db: Session, f: OpsFile) -> dict:
    stay = money.stay_of(db, f)
    tenant = db.get(Tenant, f.tenant_id)
    tz = get_tz(tenant)
    d, a = money.details(f), money.account(db, f)
    gst = Decimal(str(a["gst_percent"]))
    prop = db.query(Property.name).filter(Property.id == stay.property_id, Property.tenant_id == f.tenant_id).first()
    guest = (stay.guest.name if stay.guest is not None else None) or "Guest"
    nights = (stay.check_out - stay.check_in).days
    people = stays.names(db, f)

    package_total = _q(a["package_total"])
    package_ex = (package_total / (1 + gst / 100)).quantize(Decimal("0.01"))
    cutoff = f.dispatched_at.astimezone(tz).date() if f.dispatched_at else None  # advance = paid up to check-in day
    pays = db.query(StayPayment).filter(StayPayment.tenant_id == f.tenant_id, StayPayment.stay_id == stay.id).all()
    advance = sum(
        ((-1 if p.kind == "refund" else 1) * _q(p.amount) for p in pays if cutoff is None or p.paid_on <= cutoff),
        Decimal("0.00"),
    )
    paid, revenue, extras = _q(a["paid"]), _q(a["total_revenue"]), _q(a["addons_total"])
    by_cat = a["expenses_by_category"]
    order = list(EXPENSE_LINES) + sorted(k for k in by_cat if k not in EXPENSE_LINES)
    expenses = {k: _q(by_cat[k]) for k in order if k in by_cat}
    total_exp = _q(a["total_expenses"])
    dep = a["deposit"]

    def row(label, value, strong=False):
        return [label, value, strong]

    revised = [row("Original package total", inr_text(package_total))]
    if extras:
        revised.append(row("Extras approved during the stay", inr_text(extras)))
    revised += [
        row("Total stay revenue", inr_text(revenue), True),
        row("Amount received by check-in", inr_text(advance)),
        row("Additional amount received", inr_text(paid - advance)),
        row("Final balance", inr_text(a["outstanding"]), True),
    ]
    if dep is not None:
        kept = _q(dep["deducted"])
        revised += [
            row("Security deposit (not revenue)", inr_text(dep["amount"])),
            row(
                "Deposit decision",
                "Held, not decided yet"
                if dep["status"] == "held"
                else "Not collected"
                if dep["status"] == "pending"
                else f"{inr_text(kept)} kept, {inr_text(_q(dep['amount']) - kept)} refunded"
                + (f" ({d.deposit_reason})" if d.deposit_reason else ""),
            ),
        ]
    exp_rows = [row(EXPENSE_LINES.get(k, k.title()), inr_text(v)) for k, v in expenses.items()] or [
        row("No expenses recorded", inr_text(0))
    ]
    gst_rows = [row("Package revenue excluding GST", inr_text(package_ex))]
    if extras:
        gst_rows.append(row("Extras revenue excluding GST", inr_text(_q(a["revenue_ex_gst"]) - package_ex)))
    gst_rows += [row("Revenue excluding GST", inr_text(a["revenue_ex_gst"]), True)]
    gst_rows += [row(f"Less: {EXPENSE_LINES.get(k, k).lower()}", inr_text(v)) for k, v in expenses.items()]
    gst_rows.append(row("Net revenue excluding GST", inr_text(a["net_ex_gst"]), True))

    return {
        "business": (tenant.brand_name or tenant.name) if tenant else "",
        "title": "Stay Account Report",
        "draft": f.report_approved_at is None,
        "sub": f"{guest} | {prop[0] if prop else 'Villa'} | {stay.check_in.strftime('%B %Y')}",
        "footer": f"Stay Account Report - {guest}",
        "sections": [
            {
                "title": "1. Guest & stay details",
                "header": ("Particular", "Details"),
                "rows": [
                    row("Guest name", guest),
                    row("Contact number", _mask(stay.guest.phone if stay.guest else None)),
                    row("Villa", prop[0] if prop else "Not set"),
                    row(
                        "Stay dates",
                        f"{stay.check_in.strftime('%d %B %Y')} - {stay.check_out.strftime('%d %B %Y')} ({nights} night{'s' if nights != 1 else ''})",
                    ),
                    row("Guests", f"{stay.adults} adults" + (f" + {stay.children} kids" if stay.children else "")),
                    row("Arrival time", _hhmm(stay.check_in_time)),
                    row("Checked in", _when(f.dispatched_at, tz)),
                    row("Checked out", _when(f.returned_at, tz)),
                    row(
                        "Caretaker / cook / cleaner",
                        " / ".join(people[r] or "Not set" for r in ("caretaker", "cook", "cleaner")),
                    ),
                ],
            },
            {
                "title": "2. Package & payment summary",
                "header": ("Particular", "Amount"),
                "rows": [
                    row("Package cost", inr_text(package_ex)),
                    row(f"GST @ {gst.normalize():f}%", inr_text(package_total - package_ex)),
                    row("Original package total", inr_text(package_total), True),
                    row("Advance received", inr_text(advance)),
                    row("Balance at check-in", inr_text(max(package_total - advance, Decimal("0.00")))),
                ],
            },
            {"title": "3. Revised amount payable", "header": ("Particular", "Amount"), "rows": revised},
            {
                "title": "4. Stay expenses",
                "header": ("Expense", "Amount"),
                "rows": exp_rows + [row("Total expenses", inr_text(total_exp), True)],
            },
            {
                "title": "5. Net revenue - cash basis",
                "header": ("Particular", "Amount"),
                "rows": [
                    row("Total revenue", inr_text(revenue)),
                    row("Less: total expenses", inr_text(total_exp)),
                    row("Net cash surplus", inr_text(a["net_cash"]), True),
                ],
            },
            {
                "title": "6. GST-adjusted business revenue",
                "header": ("Particular", "Amount"),
                "rows": gst_rows,
                "note": f"Customer amounts include {gst.normalize():f}% GST, so the GST part is taken out to show business revenue.",
            },
            {
                "title": "7. Final account position",
                "header": ("Account item", "Final amount"),
                "rows": [
                    row("Total customer billing", inr_text(revenue)),
                    row("Total stay expenses", inr_text(total_exp)),
                    row("Net cash surplus", inr_text(a["net_cash"]), True),
                    row("Net revenue excluding GST", inr_text(a["net_ex_gst"]), True),
                    row("Outstanding balance", inr_text(a["outstanding"])),
                ],
            },
        ],
    }
