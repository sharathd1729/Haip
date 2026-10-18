"""Render a sent quote (the primary option and its fallback) as an A4 PDF, next to the invoice renderer (reportlab,
built-in Helvetica, "Rs. 1,25,000" because Helvetica has no rupee sign).

Only the issued snapshots are used (amounts, lines, GST, advance, at-actuals items, validity), never live records, so a
PDF rendered again later says exactly what the guest was quoted. The seller block is the invoice profile
(brand_config.invoice_profile), the same one printed on invoices.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.invoice_pdf import _BRAND, _INK, _MUTED, _RULE, _logo_image, inr_text


def _d(v) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except (ArithmeticError, ValueError):
        return Decimal(0)


def _pct(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _day(v) -> str:
    try:
        d = v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    except ValueError:
        return str(v or "")
    return f"{d:%a}, {d.day} {d:%b %Y}"


def _styles():
    base = getSampleStyleSheet()["Normal"]
    body = ParagraphStyle("qb", parent=base, fontName="Helvetica", fontSize=9, leading=12, textColor=_INK)
    return {
        "body": body,
        "small": ParagraphStyle("qs", parent=body, fontSize=8, leading=10.5, textColor=_MUTED),
        "label": ParagraphStyle("ql", parent=body, fontName="Helvetica-Bold", fontSize=8, leading=10.5, textColor=_MUTED),
        "head": ParagraphStyle("qh", parent=body, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=_BRAND, alignment=TA_RIGHT),
        "h2": ParagraphStyle("q2", parent=body, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=_INK),
        "right": ParagraphStyle("qr", parent=body, alignment=TA_RIGHT),
    }


def _option_block(title: str, snap: dict, guests: Optional[int], st: dict) -> KeepTogether:
    inputs = snap.get("inputs") or {}
    dest = (snap.get("destination") or {}).get("name")
    name = snap.get("package_name") or snap.get("package_key") or "Trip"
    adults, children = int(inputs.get("adults") or 0), int(inputs.get("children") or 0)
    people = guests if guests is not None else adults + children
    when = f"{_day(inputs.get('check_in'))} to {_day(inputs.get('check_out'))} · {people} guest{'s' if people != 1 else ''}"
    parts = [Paragraph(f"<b>{escape(title)}: {escape(dest + ' - ' if dest else '')}{escape(name)}</b>", st["h2"]),
             Paragraph(escape(when), st["small"]), Spacer(1, 2 * mm)]

    rows = [[Paragraph("<b>Item</b>", st["label"]), Paragraph("<b>Amount</b>", st["label"])]]
    for ln in snap.get("lines") or []:
        desc = escape(str(ln.get("label") or ""))
        if ln.get("detail"):
            desc += f"<br/><font size=7.5 color='#5F6B66'>{escape(str(ln['detail']))}</font>"
        amt = _d(ln.get("amount"))
        rows.append([Paragraph(desc, st["body"]),
                     Paragraph(("- " + inr_text(-amt)) if amt < 0 else inr_text(amt), st["right"])])
    gst_pct = _d(snap.get("gst_percent"))
    totals = [("Taxable value", inr_text(snap.get("taxable") if snap.get("taxable") is not None else snap.get("subtotal")), False)]
    if gst_pct > 0:
        totals.append((f"GST {_pct(gst_pct)}%", inr_text(snap.get("gst")), False))
    totals.append(("Total" + (" (incl. GST)" if gst_pct > 0 else ""), inr_text(snap.get("total")), True))
    if _d(snap.get("advance")) > 0:
        pct = _d(snap.get("advance_percent"))
        balance = _d(snap.get("total")) - _d(snap.get("advance"))
        label = f"Advance to confirm ({_pct(pct)}%)" if pct > 0 else "Advance to confirm"
        totals.append((label, inr_text(snap.get("advance")), True))
        totals.append(("Balance before travel begins", inr_text(balance), False))
    for label, amount, bold in totals:
        fmt = "<b>%s</b>" if bold else "%s"
        rows.append([Paragraph(fmt % escape(label), st["body"]), Paragraph(fmt % escape(amount), st["right"])])
    first_total = len(rows) - len(totals)
    t = Table(rows, colWidths=[140 * mm, 40 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _RULE), ("LINEBELOW", (0, 1), (-1, first_total - 1), 0.3, _RULE),
        ("LINEABOVE", (0, first_total), (-1, first_total), 0.6, _RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    parts.append(t)
    for item in snap.get("at_actuals") or []:
        parts.append(Paragraph(f"{escape(str(item))}: billed at actuals, not in the total.", st["small"]))
    if snap.get("inclusions"):
        parts.append(Paragraph("Includes: " + escape(", ".join(str(i) for i in snap["inclusions"])), st["small"]))
    if snap.get("exclusions"):
        parts.append(Paragraph("Not included: " + escape(", ".join(str(i) for i in snap["exclusions"])), st["small"]))
    return KeepTogether(parts + [Spacer(1, 6 * mm)])


def render(*, number: str, issued_on: date, valid_until, seller: dict, buyer: dict, options: list[dict],
           logo: Optional[bytes] = None) -> bytes:
    """``options`` = [{"title": "Option 1", "snapshot": {...}, "guests": int|None, "pay_url": str|None}] in rank order."""
    st = _styles()
    seller_lines = [f"<b>{escape(seller.get('legal_name') or '')}</b>"]
    if seller.get("address"):
        seller_lines.append(escape(seller["address"]).replace("\n", "<br/>"))
    if seller.get("gstin"):
        seller_lines.append(f"GSTIN {escape(seller['gstin'])}")
    left = [x for x in (_logo_image(logo),) if x] + [Paragraph("<br/>".join(seller_lines), st["body"])]
    meta = [f"<b>Quote {escape(number)}</b>", f"Date: {_day(issued_on)}", f"Valid until: {_day(valid_until)}"]
    header = Table([[left, [Paragraph("Quotation", st["head"]), Spacer(1, 2 * mm), Paragraph("<br/>".join(meta), st["right"])]]],
                   colWidths=[100 * mm, 80 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    guest = [f"<b>{escape(buyer.get('name') or 'Guest')}</b>"] + [escape(str(buyer[k])) for k in ("phone", "email") if buyer.get(k)]

    story = [header, Spacer(1, 8 * mm), Paragraph("PREPARED FOR", st["label"]), Paragraph("<br/>".join(guest), st["body"]),
             Spacer(1, 6 * mm)]
    for opt in options:
        story.append(_option_block(opt["title"], opt.get("snapshot") or {}, opt.get("guests"), st))
        if opt.get("pay_url"):
            story.append(Paragraph(f"Pay the advance for {escape(opt['title'].lower())}: {escape(opt['pay_url'])}", st["small"]))
            story.append(Spacer(1, 4 * mm))
    if len(options) > 1:
        story.append(Paragraph("Each option has its own payment link. Pay for the one you choose; the other is withdrawn.", st["small"]))
    story.append(Paragraph("Tolls and parking are billed at actuals after the trip. Prices are held until the date above; "
                           "your dates are confirmed when the advance is received and the caravan is still free.", st["small"]))
    story.append(Paragraph("This is a computer-generated document and needs no signature.", st["small"]))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"Quote {number}", author=seller.get("legal_name") or "")
    doc.build(story)
    return buf.getvalue()
