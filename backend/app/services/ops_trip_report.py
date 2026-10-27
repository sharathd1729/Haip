"""Trip Account Report PDF, the same seven sections as Ratha's hand-made Saleem report (Aug 2026):
1 guest & trip, 2 package & payment, 3 kilometres + revised amount payable, 4 expenses, 5 net cash, 6 GST-adjusted revenue,
7 final position.

`build` turns the file into plain rows (every number from ops_money.account and the booking ledger, so the report, the trip
screen and the invoice cannot disagree); `render` only draws them. Internal document: watermarked with the business name,
"DRAFT" until the manager approves the report. The guest's number is masked to its last four digits.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.core.tenant_tz import get_tz
from app.models.ops_files import OpsFile
from app.models.property import Property
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.services import ops_money as money
from app.services import ops_rates
from app.services.invoice_pdf import inr_text

EXPENSE_LINES = {
    "driver": "Driver hiring expense",
    "helper": "Helper expense",
    "fuel": "Diesel / fuel cost",
    "toll": "Tolls",
    "parking": "Parking",
    "repair": "Repairs",
    "consumables": "Consumables",
    "groceries": "Groceries",
    "other": "Other expenses",
}
_P = Decimal("0.01")


def _q(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(_P)


def _mask(phone: str | None) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"xxxxxx{digits[-4:]}" if len(digits) >= 4 else "Not recorded"


def _when(dt: datetime | None, tz) -> str:
    return dt.astimezone(tz).strftime("%d %B %Y, %I:%M %p").lstrip("0").replace(" 0", " ") if dt else "Not yet"


def _hhmm(t: str | None) -> str:
    if not t:
        return "Not set"
    try:
        return datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return t


def build(db: Session, f: OpsFile) -> dict:
    """Every row of the report: {title, sub, draft, business, sections: [{title, note?, header, rows: [[label, value, strong]]}]}."""
    stay = money.stay_of(db, f)
    tenant = db.get(Tenant, f.tenant_id)
    tz = get_tz(tenant)
    d, a = money.details(f), money.account(db, f)
    gst = Decimal(str(a["gst_percent"]))
    prop = db.query(Property.name).filter(Property.id == stay.property_id, Property.tenant_id == f.tenant_id).first()
    q = ops_rates.booking_quote(db, stay)
    package_name = ((q.snapshot or {}).get("package_name") if q is not None else None) or (
        f"{(stay.check_out - stay.check_in).days} days" + (f" / {int(d.allowance_km):,} km" if d.allowance_km else "")
    )
    guest = (stay.guest.name if stay.guest is not None else None) or "Guest"

    package_total = _q(a["package_total"])
    package_ex = (package_total / (1 + gst / 100)).quantize(_P)
    # Advance = money received up to the day the trip left (all of it when it has not left yet).
    cutoff = f.dispatched_at.astimezone(tz).date() if f.dispatched_at else None
    pays = db.query(StayPayment).filter(StayPayment.tenant_id == f.tenant_id, StayPayment.stay_id == stay.id).all()

    def signed(p):
        return (-1 if p.kind == "refund" else 1) * _q(p.amount)

    advance = sum(
        (signed(p) for p in pays if cutoff is None or p.paid_on <= cutoff),
        Decimal("0.00"),
    )
    paid = _q(a["paid"])
    km_charge = _q(a["extra_km_charge"]) if d.extra_km_addon_id else Decimal("0.00")
    other_extras = _q(a["addons_total"]) - km_charge
    revenue = _q(a["total_revenue"])
    by_cat = a["expenses_by_category"]
    order = list(EXPENSE_LINES) + sorted(k for k in by_cat if k not in EXPENSE_LINES)
    expenses = {k: _q(by_cat[k]) for k in order if k in by_cat}  # Saleem order: driver, helper, fuel, ...
    total_exp = _q(a["total_expenses"])
    rate = d.extra_km_rate
    rate_text = (
        f"Rs. {rate:,}/km ({'including' if d.rate_includes_gst else 'plus'} {gst.normalize():f}% GST)"
        if rate is not None
        else "Not set"
    )

    def row(label, value, strong=False):
        return [label, value, strong]

    km = [
        row(
            "Starting meter reading",
            f"{d.start_odometer:,} km" if d.start_odometer else "Not yet",
        ),
        row(
            "Ending meter reading",
            f"{d.end_odometer:,} km" if d.end_odometer else "Not yet",
        ),
        row(
            "Actual distance travelled",
            f"{a['distance_km']:,} km" if a["distance_km"] is not None else "Not yet",
        ),
        row(
            "Package allowance",
            f"{int(d.allowance_km):,} km" if d.allowance_km else "Not set",
        ),
        row("Extra kilometres", f"{a['extra_km']:,} km"),
        row("Extra km rate", rate_text),
        row("Extra km charges", inr_text(km_charge)),
    ]
    revised = [
        row("Original package total", inr_text(package_total)),
        row("Extra km charges", inr_text(km_charge)),
    ]
    if other_extras:
        revised.append(row("Extras approved during the trip", inr_text(other_extras)))
    revised += [
        row("Total trip revenue", inr_text(revenue), True),
        row("Amount already received", inr_text(advance)),
        row("Additional amount received", inr_text(paid - advance)),
        row("Final balance", inr_text(a["outstanding"]), True),
    ]
    exp_rows = [row(EXPENSE_LINES.get(k, k.title()), inr_text(v)) for k, v in expenses.items()] or [
        row("No expenses recorded", inr_text(0))
    ]
    km_ex = (km_charge / (1 + gst / 100)).quantize(_P)
    extras_ex = (_q(a["revenue_ex_gst"]) - package_ex - km_ex).quantize(_P)
    gst_rows = [
        row("Package revenue excluding GST", inr_text(package_ex)),
        row("Extra km revenue excluding GST", inr_text(km_ex)),
    ]
    if other_extras:
        gst_rows.append(row("Extras revenue excluding GST", inr_text(extras_ex)))
    gst_rows += [row("Revenue excluding GST", inr_text(a["revenue_ex_gst"]), True)]
    gst_rows += [row(f"Less: {EXPENSE_LINES.get(k, k).lower()}", inr_text(v)) for k, v in expenses.items()]
    gst_rows.append(row("Net revenue excluding GST", inr_text(a["net_ex_gst"]), True))

    return {
        "business": (tenant.brand_name or tenant.name) if tenant else "",
        "title": "Trip Account Report",
        "draft": f.report_approved_at is None,
        "sub": f"{guest} | {d.route or 'Route not set'} | {stay.check_in.strftime('%B %Y')}",
        "footer": f"Trip Account Report - {guest}",
        "sections": [
            {
                "title": "1. Guest & trip details",
                "header": ("Particular", "Details"),
                "rows": [
                    row("Guest name", guest),
                    row(
                        "Contact number",
                        _mask(stay.guest.phone if stay.guest else None),
                    ),
                    row("Vehicle", prop[0] if prop else "Not set"),
                    row("Route", d.route or "Not set"),
                    row(
                        "Travel dates",
                        f"{stay.check_in.strftime('%d %B %Y')} - {stay.check_out.strftime('%d %B %Y')}",
                    ),
                    row(
                        "Guests",
                        f"{stay.adults} adults" + (f" + {stay.children} kids" if stay.children else ""),
                    ),
                    row("Package", package_name),
                    row("Reporting time", _hhmm(stay.check_in_time)),
                    row("Trip start", _when(f.dispatched_at, tz)),
                    row("Trip end", _when(f.returned_at, tz)),
                ],
            },
            {
                "title": "2. Package & payment summary",
                "header": ("Particular", "Amount"),
                "rows": [
                    row("Package cost", inr_text(package_ex)),
                    row(
                        f"GST @ {gst.normalize():f}%",
                        inr_text(package_total - package_ex),
                    ),
                    row("Original package total", inr_text(package_total), True),
                    row("Advance received", inr_text(advance)),
                    row(
                        "Balance before extra km",
                        inr_text(max(package_total - advance, Decimal("0.00"))),
                    ),
                ],
            },
            {
                "title": "3. Kilometre calculation",
                "header": ("Particular", "Calculation / result"),
                "rows": km,
                "then": {
                    "title": "Revised amount payable",
                    "header": ("Particular", "Amount"),
                    "rows": revised,
                },
            },
            {
                "title": "4. Trip expenses",
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
                    row("Total trip expenses", inr_text(total_exp)),
                    row("Net cash surplus", inr_text(a["net_cash"]), True),
                    row("Net revenue excluding GST", inr_text(a["net_ex_gst"]), True),
                    row("Outstanding balance", inr_text(a["outstanding"])),
                ],
            },
        ],
    }


# ── Drawing ─────────────────────────────────────────────────────────────────

_BAND = colors.HexColor("#0B2B26")
_HEAD = colors.HexColor("#EEF2EF")
_STRONG = colors.HexColor("#E8F5EC")
_RULE = colors.HexColor("#9AA5A0")
_MARK = colors.HexColor("#C9CFCC")


def _latin(text) -> str:
    """Built-in Helvetica draws Latin-1 only: arrows and the rupee sign become words, anything else a "?" (never a box)."""
    t = str(text).replace("→", "->").replace("₹", "Rs. ").replace("–", "-").replace("—", "-")
    return t.encode("latin-1", "replace").decode("latin-1")


def _safe(text) -> str:
    """Text for a Paragraph (reportlab markup): Latin-1 and escaped."""
    return escape(_latin(text))


def _table(header, rows, cell, cell_b, right, right_b) -> Table:
    data = [[Paragraph(header[0], cell_b), Paragraph(header[1], right_b)]]
    data += [
        [
            Paragraph(_safe(label), cell_b if s else cell),
            Paragraph(_safe(v), right_b if s else right),
        ]
        for label, v, s in rows
    ]
    t = Table(data, colWidths=[88 * mm, 88 * mm])
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, _RULE),
        ("BACKGROUND", (0, 0), (-1, 0), _HEAD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    style += [("BACKGROUND", (0, i + 1), (-1, i + 1), _STRONG) for i, r in enumerate(rows) if r[2]]
    t.setStyle(TableStyle(style))
    return t


def render(report: dict) -> bytes:
    buf = io.BytesIO()
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=1)
    sub = ParagraphStyle(
        "s",
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        alignment=1,
        textColor=colors.HexColor("#5F6B66"),
    )
    band = ParagraphStyle("b", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.white)
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=9, leading=11.5)
    cell_b = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")
    right = ParagraphStyle("r", parent=cell, alignment=2)
    right_b = ParagraphStyle("rb", parent=cell_b, alignment=2)
    note = ParagraphStyle("n", parent=cell, fontSize=8.5, textColor=colors.HexColor("#3B4743"))
    label = ParagraphStyle("l", parent=cell_b, fontSize=9.5)

    def section_band(text):
        t = Table([[Paragraph(escape(text.upper()), band)]], colWidths=[176 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _BAND),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        return t

    story = [
        Paragraph(_safe(report["title"].upper()), title),
        Spacer(1, 3 * mm),
        Paragraph(_safe(report["sub"]), sub),
        Spacer(1, 5 * mm),
    ]
    for s in report["sections"]:
        block = [section_band(s["title"])]
        if s.get("note"):
            block += [Spacer(1, 1.5 * mm), Paragraph(escape(s["note"]), note)]
        block += [
            Spacer(1, 1.5 * mm),
            _table(s["header"], s["rows"], cell, cell_b, right, right_b),
        ]
        story.append(KeepTogether(block))
        if s.get("then"):
            th = s["then"]
            story += [
                Spacer(1, 3 * mm),
                KeepTogether(
                    [
                        Paragraph(escape(th["title"]), label),
                        Spacer(1, 1.5 * mm),
                        _table(th["header"], th["rows"], cell, cell_b, right, right_b),
                    ]
                ),
            ]
        story.append(Spacer(1, 5 * mm))

    mark = ("DRAFT - " if report["draft"] else "") + (report["business"] or "").upper() + " CONFIDENTIAL"

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 46)
        canvas.setFillColor(_MARK)
        canvas.setFillAlpha(0.35)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(52)
        canvas.drawCentredString(0, 0, _latin(mark[:40]))
        canvas.restoreState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#5F6B66"))
        canvas.drawCentredString(A4[0] / 2, 12 * mm, _latin(f"{report['footer']} - page {doc.page}"))

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=report["title"],
        author=report["business"] or "HAIP",
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buf.getvalue()
