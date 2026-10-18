"""Property assessment report as an A4 PDF (reportlab, built-in Helvetica: no font files, "Rs. 1,25,000").

Renders ONLY the stored snapshot (the result the visitor was shown and the benchmark version it names), never a
recomputation, so a later benchmark change never alters a report someone already has.
"""
from __future__ import annotations

import io
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.invoice_pdf import inr_text

_INK = colors.HexColor("#1F2A27")
_MUTED = colors.HexColor("#5F6B66")
_RULE = colors.HexColor("#D9DED9")
_BRAND = colors.HexColor("#1E7A5A")
_ZONE_FILL = {"rooms": "#1E7A5A", "common": "#5FA88B", "venue": "#E0694A", "amenities": "#F2B05E",
              "parking": "#9AA5A0", "green": "#CFE8D6"}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=17, textColor=_INK, alignment=0),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=_BRAND, spaceBefore=6),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=_INK),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=11, textColor=_MUTED),
        "right": ParagraphStyle("r", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, alignment=2, textColor=_INK),
    }


def _text(s: str) -> str:
    """Helvetica has no rupee sign: write Rs."""
    return escape(str(s).replace("₹", "Rs. "))


def _table(rows: list[list], widths: list[float], st) -> Table:
    data = [[Paragraph(f"<b>{_text(c)}</b>", st["body"] if i == 0 else st["right"]) for i, c in enumerate(rows[0])]]
    for r in rows[1:]:
        data.append([Paragraph(_text(c), st["body"] if i == 0 else st["right"]) for i, c in enumerate(r)])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, _RULE), ("LINEBELOW", (0, 1), (-1, -1), 0.25, _RULE),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _sketch(zoning: dict) -> Drawing:
    w_mm, h_mm = 150 * mm, 100 * mm
    sx, sy = w_mm / zoning["width"], h_mm / zoning["height"]
    d = Drawing(w_mm, h_mm)
    for z in zoning["zones"]:
        x, y = z["x"] * sx, h_mm - (z["y"] + z["h"]) * sy        # canvas origin is bottom-left
        d.add(Rect(x, y, z["w"] * sx, z["h"] * sy, fillColor=colors.HexColor(_ZONE_FILL.get(z["key"], "#DDDDDD")),
                   strokeColor=colors.white, strokeWidth=1.5))
        if z["w"] * sx > 22 * mm and z["h"] * sy > 8 * mm:
            d.add(String(x + 2 * mm, y + z["h"] * sy - 5 * mm, z["label"][:28], fontName="Helvetica-Bold", fontSize=7,
                         fillColor=colors.white if z["key"] in ("rooms", "common", "venue") else _INK))
            d.add(String(x + 2 * mm, y + z["h"] * sy - 9 * mm, f"{z['sqft']:,} sq ft", fontName="Helvetica", fontSize=6.5,
                         fillColor=colors.white if z["key"] in ("rooms", "common", "venue") else _INK))
    return d


def render(result: dict, *, narrative: Optional[str] = None, prepared_for: Optional[str] = None) -> bytes:
    st = _styles()
    y, inv, pay = result["yearly"], result["investment"], result["payback_months"]
    story = [Paragraph("Property assessment", st["title"]),
             Paragraph(_text(f"{result['property_type_label']} · {result['segment_label']} · {result['keys']} rooms · "
                             f"{result['plot_sqft']:,} sq ft · {result['location_label']}"), st["body"])]
    if prepared_for:
        story.append(Paragraph(f"Prepared for {_text(prepared_for)}", st["small"]))
    sample = " (SAMPLE values, owner to confirm)" if result.get("benchmark_sample") else ""
    story += [Paragraph(_text(f"Benchmarks: {result['benchmark_label']}, version {result['benchmark_version']}{sample}"), st["small"]),
              Spacer(1, 4 * mm)]
    if narrative:
        story += [Paragraph(_text(narrative).replace("\n", "<br/>"), st["body"]), Spacer(1, 3 * mm)]

    story.append(Paragraph("Yearly projection", st["h2"]))
    rows = [["", "Low", "Likely", "High"]]
    for label, key in (("Revenue", "revenue"), ("Rooms", "room_revenue"), ("Experiences and food", "extras_revenue"),
                       ("Events", "event_revenue"), ("OTA commission", "ota_commission"), ("Running costs", "running_costs"),
                       ("Net operating income", "net_operating_income")):
        rows.append([label] + [inr_text(y[s][key], paise=False) for s in ("low", "likely", "high")])
    rows.append(["Average occupancy"] + [f"{round(y[s]['average_occupancy'] * 100)}%" for s in ("low", "likely", "high")])
    rows.append(["Payback"] + [f"{pay[s]} months" if pay[s] else "No payback" for s in ("low", "likely", "high")])
    story.append(_table(rows, [62 * mm, 39 * mm, 39 * mm, 40 * mm], st))

    story.append(Paragraph("Month by month", st["h2"]))
    rows = [["Month", "Occupancy (likely)", "Low", "Likely", "High"]]
    for m in result["monthly"]:
        rows.append([m["month"], f"{round(m['occupancy']['likely'] * 100)}%"]
                    + [inr_text(m["revenue"][s], paise=False) for s in ("low", "likely", "high")])
    story.append(_table(rows, [24 * mm, 36 * mm, 40 * mm, 40 * mm, 40 * mm], st))

    story.append(Paragraph("Investment estimate", st["h2"]))
    rows = [["Item", "Amount"],
            [f"Build ({inv['built_up_sqft']:,} sq ft built up, {'conversion' if inv['build_status'] == 'conversion' else 'new build'})",
             inr_text(inv["build_cost"], paise=False)],
            ["Fit-out", inr_text(inv["fitout"], paise=False)], ["Amenities", inr_text(inv["amenities"], paise=False)],
            ["Contingency", inr_text(inv["contingency"], paise=False)], ["Total", inr_text(inv["total"], paise=False)]]
    story.append(_table(rows, [130 * mm, 50 * mm], st))
    story.append(Paragraph(_text(f"Running costs {round(result['running_cost_pct'] * 100)}% of revenue · OTA share "
                                 f"{round(result['ota_share'] * 100)}% of room revenue at {round(result['ota_commission_pct'] * 100)}% commission"),
                           st["small"]))

    zoning = result["zoning"]
    story.append(KeepTogether([Paragraph("Indicative zoning sketch", st["h2"]), _sketch(zoning),
                               Paragraph("Indicative block plan sized to the plot, not an architectural drawing.", st["small"])]))

    story.append(Paragraph("Assumptions", st["h2"]))
    story += [Paragraph("• " + _text(a), st["small"]) for a in result["assumptions"]]
    if result.get("warnings"):
        story.append(Paragraph("Watch out", st["h2"]))
        story += [Paragraph("• " + _text(w), st["small"]) for w in result["warnings"]]

    cta = result.get("cta") or {}
    if cta:
        story.append(Paragraph("Run it with HAIP", st["h2"]))
        for key in ("saas", "service"):
            o = cta.get(key)
            if o:
                story.append(Paragraph(f"<b>{_text(o['title'])}</b>: {_text(o['text'])} {_text(o['price_text'])}", st["body"]))
    story += [Spacer(1, 4 * mm), Paragraph(_text(result["disclaimer"]), st["small"])]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Property assessment", author="HAIP")
    doc.build(story)
    return buf.getvalue()
