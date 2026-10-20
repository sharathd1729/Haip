"""Render an issued invoice or receipt as an A4 PDF (reportlab, built-in Helvetica: no font files).

Only the snapshot on the Invoice row is used, never the live booking, so a PDF re-rendered later says exactly what
was issued. Money is printed as "Rs. 1,25,000" (Indian digit grouping; Helvetica has no rupee sign).
"""
from __future__ import annotations

import base64
import io
from decimal import Decimal
from typing import Optional
from xml.sax.saxutils import escape

import structlog
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.invoice import Invoice

log = structlog.get_logger()

TOLLS_NOTE = "Tolls and parking are billed at actuals after the trip."
_INK = colors.HexColor("#1F2A27")
_MUTED = colors.HexColor("#5F6B66")
_RULE = colors.HexColor("#D9DED9")
_BRAND = colors.HexColor("#1E7A5A")
_MAX_LOGO_BYTES = 2 * 1024 * 1024


def inr_text(value, paise: bool = True) -> str:
    """Rs. with Indian grouping: 125000 -> "Rs. 1,25,000"; 45.5 -> "Rs. 45.50"; whole rupees drop the paise."""
    d = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    sign = "-" if d < 0 else ""
    d = abs(d)
    rupees, cents = divmod(int(d * 100), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    frac = f".{cents:02d}" if paise and cents else ""
    return f"{sign}Rs. {s}{frac}"


def _logo_image(logo: Optional[bytes]):
    """Re-encode the logo with Pillow (drops anything that is not a plain image) and fit it in 45 x 18 mm."""
    if not logo or len(logo) > _MAX_LOGO_BYTES:
        return None
    try:
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(logo)) as im:
            im.load()
            im = im.convert("RGBA")
            im.thumbnail((900, 360))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
        buf.seek(0)
        w, h = ImageReader(buf).getSize()
        buf.seek(0)
        scale = min(45 * mm / w, 18 * mm / h)
        return Image(buf, width=w * scale, height=h * scale)
    except Exception as exc:  # noqa: BLE001  -- a bad logo must never stop an invoice
        log.warning("invoice_logo_unreadable", error=str(exc))
        return None


def logo_from_data_url(url: Optional[str]) -> Optional[bytes]:
    """Branding stores an uploaded logo as a data: URL. Never fetch an http(s) logo here (no outbound calls)."""
    if not url or not url.startswith("data:image/") or ";base64," not in url[:60]:
        return None
    try:
        raw = base64.b64decode(url.split(",", 1)[1], validate=False)
    except (ValueError, IndexError):
        return None
    return raw if len(raw) <= _MAX_LOGO_BYTES else None


def _title(inv: Invoice) -> str:
    if inv.kind == "receipt":
        return "Payment receipt"
    if inv.kind == "credit_note":
        return "Credit note"
    return "Tax invoice" if (inv.seller or {}).get("gstin") else "Invoice"


def render(inv: Invoice, logo: Optional[bytes] = None) -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=_INK)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10.5, textColor=_MUTED)
    label = ParagraphStyle("l", parent=small, fontName="Helvetica-Bold", textColor=_MUTED)
    head = ParagraphStyle("h", parent=body, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=_BRAND, alignment=TA_RIGHT)
    right = ParagraphStyle("r", parent=body, alignment=TA_RIGHT)
    seller, buyer = inv.seller or {}, inv.buyer or {}
    p = lambda text, style=body: Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)  # noqa: E731

    seller_lines = [f"<b>{escape(seller.get('legal_name') or '')}</b>"]
    if seller.get("address"):
        seller_lines.append(escape(seller["address"]).replace("\n", "<br/>"))
    if seller.get("gstin"):
        seller_lines.append(f"GSTIN {escape(seller['gstin'])}")
    if seller.get("state"):
        seller_lines.append(f"State: {escape(seller['state'])} ({escape(seller.get('state_code') or '')})")
    left = [x for x in (_logo_image(logo),) if x] + [Paragraph("<br/>".join(seller_lines), body)]

    meta = [f"<b>{escape(inv.number)}</b>", f"Date: {inv.issued_at:%d %b %Y}"]
    if inv.booking_ref:
        meta.append(f"Booking {escape(inv.booking_ref)}")
    if inv.kind == "invoice" and inv.place_of_supply:
        meta.append(f"Place of supply: {escape(buyer.get('state') or inv.place_of_supply)} ({escape(inv.place_of_supply)})")
    if inv.notes:
        meta.append(escape(inv.notes))
    header = Table([[left, [Paragraph(_title(inv), head), Spacer(1, 2 * mm), Paragraph("<br/>".join(meta), right)]]],
                   colWidths=[100 * mm, 80 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    billed = [f"<b>{escape(buyer.get('name') or 'Guest')}</b>"]
    for key, prefix in (("phone", ""), ("email", ""), ("gstin", "GSTIN ")):
        if buyer.get(key):
            billed.append(prefix + escape(str(buyer[key])))
    billed_to = [Paragraph("BILLED TO" if inv.kind != "receipt" else "RECEIVED FROM", label), Paragraph("<br/>".join(billed), body)]

    story = [header, Spacer(1, 8 * mm), *billed_to, Spacer(1, 6 * mm)]
    story.append(_lines_table(inv, p, small, right))
    story.append(Spacer(1, 4 * mm))
    story.append(_totals_table(inv, body, right))
    story.append(Spacer(1, 8 * mm))
    if inv.kind == "invoice":
        story.append(p(TOLLS_NOTE, small))
    if seller.get("sac_code") and inv.kind == "invoice":
        story.append(p(f"SAC {seller['sac_code']}", small))
    story.append(p("This is a computer-generated document and needs no signature.", small))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"{_title(inv)} {inv.number}", author=seller.get("legal_name") or "")
    doc.build(story)
    return buf.getvalue()


def _lines_table(inv: Invoice, p, small, right) -> Table:
    taxed = inv.kind == "invoice" and Decimal(str(inv.gst_rate or 0)) > 0
    rows = [["Item", "Taxable value" if taxed else "", "Amount"]]
    for ln in inv.lines or []:
        desc = [p(ln.get("description")), *([p(ln["detail"], small)] if ln.get("detail") else [])]
        rows.append([desc, Paragraph(inr_text(ln.get("taxable")), right) if taxed else "", Paragraph(inr_text(ln.get("amount")), right)])
    t = Table(rows, colWidths=[110 * mm, 35 * mm, 35 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED), ("ALIGN", (1, 0), (-1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _RULE), ("LINEBELOW", (0, 1), (-1, -1), 0.3, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _pct(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _totals_table(inv: Invoice, body, right) -> Table:
    rows: list[list[str]] = []
    rate = Decimal(str(inv.gst_rate or 0))
    if inv.kind == "invoice":
        if rate > 0:
            rows.append(["Taxable value", inr_text(inv.taxable_value)])
            if Decimal(str(inv.igst or 0)) > 0:
                rows.append([f"IGST {_pct(rate)}%", inr_text(inv.igst)])
            else:
                half = _pct(rate / 2)
                rows += [[f"CGST {half}%", inr_text(inv.cgst)], [f"SGST {half}%", inr_text(inv.sgst)]]
        rows.append(["Total" + (" (incl. GST)" if rate > 0 else ""), inr_text(inv.total)])
        rows.append(["Received so far", inr_text(inv.amount_received)])
        rows.append(["Balance due before travel", inr_text(inv.balance_due)])
        bold = {len(rows) - 3, len(rows) - 1}
    else:
        rows = [["Amount received", inr_text(inv.total)], ["Received so far for this booking", inr_text(inv.amount_received)],
                ["Balance due", inr_text(inv.balance_due)]]
        bold = {0, 2}
    data = [[Paragraph(("<b>%s</b>" if i in bold else "%s") % escape(a), body),
             Paragraph(("<b>%s</b>" if i in bold else "%s") % escape(b), right)] for i, (a, b) in enumerate(rows)]
    t = Table(data, colWidths=[145 * mm, 35 * mm])
    t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("LINEABOVE", (0, min(bold)), (-1, min(bold)), 0.6, _RULE)]))
    return t
