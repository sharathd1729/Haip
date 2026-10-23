"""The brief as an A4 PDF (reportlab, built-in Helvetica; the same tooling as invoices, quotes and the impact view).

Aggregates and the brief's text only: health checks, the journey, team rows (first names of staff), demand and money. Guest
quotes appear only as the anonymised evidence lines (first name, numbers masked). Money is printed only when the reader may
see revenue (``money=False`` prints "restricted").
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.invoice_pdf import inr_text

_INK = colors.HexColor("#1F2A27")
_RULE = colors.HexColor("#D5E7DA")
_STATUS = {"green": colors.HexColor("#235347"), "amber": colors.HexColor("#8A6D00"), "red": colors.HexColor("#B3261E"),
           "no_data": colors.HexColor("#5F6B66")}


def _p(text: str, style) -> Paragraph:
    return Paragraph(escape(str(text or "").replace("₹", "Rs. ")), style)      # Helvetica has no rupee glyph


def render(report: dict, *, brand_name: str, money: bool = True) -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=_INK)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, textColor=_INK)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, textColor=_INK, spaceBefore=8)
    b, f = report.get("brief") or {}, report.get("facts") or {}
    period = report.get("period") or {}
    story = [_p(f"{brand_name} · {f.get('kind_label', 'Report')} · {period.get('from')} to {period.get('to')}", h1),
             _p(b.get("headline"), body), Spacer(1, 4 * mm)]

    rows = [["Health check", "Status"]] + [[c["label"], c["status"].replace("_", " ")] for c in f.get("health", [])]
    t = Table(rows, colWidths=[110 * mm, 50 * mm])
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE)]
    for i, c in enumerate(f.get("health", []), start=1):
        style.append(("TEXTCOLOR", (1, i), (1, i), _STATUS.get(c["status"], _INK)))
    t.setStyle(TableStyle(style))
    story += [t]

    for title, key in (("What's working", "working"), ("What's not working", "not_working")):
        items = b.get(key) or []
        if items:
            story += [_p(title, h2)] + [_p(f"• {x}", body) for x in items]
    for title, key in (("Why enquiries were lost", "why_lost"), ("Why DMs did not become leads", "why_dms_not_leads"),
                       ("Team", "team"), ("Demand", "demand"), ("Last time", "last_week_followup")):
        if b.get(key):
            story += [_p(title, h2), _p(b[key], body)]
    rev = (f.get("journey") or {}).get("revenue") or {}
    story += [_p("Money", h2)]
    if money:
        story += [_p(f"{rev.get('bookings', 0)} bookings, booked value {inr_text(rev.get('booked_value', 0), paise=False)}, "
                     f"collected {inr_text(rev.get('collected', 0), paise=False)}.", body)]
        if b.get("money"):
            story += [_p(b["money"], body)]
    else:
        story += [_p("Restricted: you do not have access to revenue figures.", body)]
    recs = b.get("recommendations") or []
    if recs:
        story += [_p("Recommendations", h2)]
        story += [_p(f"• {r.get('action')} ({r.get('owner_role')}, {r.get('due')})", body) for r in recs]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                      title=f"{brand_name} {f.get('kind_label', 'report')}").build(story)
    return buf.getvalue()
