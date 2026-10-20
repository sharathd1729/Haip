"""The impact view as a one-to-two page A4 PDF for sales decks (reportlab, built-in Helvetica).

Aggregates only: the tiles, response time by channel and by responder, the lead cohort, missed calls and lost reasons. No guest,
staff, phone, message or booking appears. Money tiles and the monthly revenue table are printed only when the viewer may see
revenue (the view already marks them restricted otherwise). Every number carries its period.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.impact_metrics import CHANNELS
from app.services.invoice_pdf import inr_text

_INK = colors.HexColor("#1F2A27")
_MUTED = colors.HexColor("#5F6B66")
_RULE = colors.HexColor("#D9DED9")
_BRAND = colors.HexColor("#1E7A5A")
_CHANNEL = {"whatsapp_cloud": "WhatsApp (business number)", "personal_whatsapp": "WhatsApp (team phones, read-only mirror)",
            "instagram": "Instagram"}
_RESPONDER = {"ai": "AI on its own", "staff_ai_draft": "Staff, sending an AI draft", "staff": "Staff"}


def fmt(value, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "%":
        return f"{value:g}%"
    if unit == "minutes":
        v = float(value)
        if v >= 120:
            return f"{v / 60:.1f} h"
        return f"{v:g} min"
    if unit == "inr":
        return inr_text(value, paise=False)
    return f"{value:g}"


def _change_text(c) -> str:
    if not c:
        return "-"
    sign = "+" if c["value"] > 0 else ""
    return f"{sign}{c['value']:g} {'pts' if c['kind'] == 'points' else '%'}"


def _mins(seconds) -> str:
    return fmt(round(seconds / 60, 1), "minutes") if seconds is not None else "-"


def _table(rows, widths, header=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED)]
    t.setStyle(TableStyle(style))
    return t


def render(view: dict, *, brand_name: str) -> bytes:
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=17, textColor=_BRAND, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, textColor=_INK, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("b", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, textColor=_MUTED, leading=11)
    w = view["windows"]
    before_p, with_p = f"{w['before']['from']} to {w['before']['to']}", f"{w['with']['from']} to {w['with']['to']}"
    story = [Paragraph(escape(f"{brand_name}: before and with HAIP"), h1),
             Paragraph(escape(f"HAIP went live on {view['go_live']}. Before = owner-entered figures (period as stated) or, where "
                              f"none, what HAIP recorded {before_p}. With HAIP = measured {with_p} (IST days)."), body)]

    rows = [["Metric", "Before HAIP", "With HAIP", "Change"]]
    for t in view["tiles"]:
        if t.get("restricted"):
            continue
        owner, measured = t["before"]["owner"], t["before"]["measured"]
        if owner:
            before = f"{fmt(owner['value'], t['unit'])} (owner-entered, {owner['period_label']})"
        elif measured["value"] is not None:
            before = f"{fmt(measured['value'], t['unit'])} (measured)"
        else:
            before = "-"
        rows.append([Paragraph(escape(t["label"]), body), Paragraph(escape(before), body), fmt(t["with"]["value"], t["unit"]),
                     _change_text(t["change"])])
    story += [Paragraph("Headline numbers", h2), _table(rows, [55 * mm, 60 * mm, 30 * mm, 25 * mm])]

    rep = view["with"]["replies"]
    rows = [["Channel (with HAIP)", "Guest turns", "Answered", "Median", "p90", "Within 15 min"]]
    for key in CHANNELS:
        s = rep["by_channel"][key]
        rows.append([_CHANNEL[key], s["turns"], fmt(s["answered_pct"], "%"), _mins(s["median_seconds"]), _mins(s["p90_seconds"]),
                     fmt(s["within_pct"]["15"], "%")])
    story += [Paragraph(f"First reply by channel, {escape(with_p)}", h2), _table(rows, [60 * mm, 20 * mm, 20 * mm, 22 * mm, 22 * mm, 26 * mm])]
    rows = [["Who replied first", "Turns answered", "Median", "p90", "Within 15 min"]]
    for key, label in _RESPONDER.items():
        s = rep["by_responder"][key]
        rows.append([label, s["answered"], _mins(s["median_seconds"]), _mins(s["p90_seconds"]), fmt(s["within_15_pct"], "%")])
    ah = rep["after_hours"]
    story += [_table(rows, [60 * mm, 28 * mm, 26 * mm, 26 * mm, 30 * mm]), Spacer(1, 3),
              Paragraph(escape(f"After hours: {ah['turns']} guest turns, {fmt(ah['within_15_pct'], '%')} answered within 15 min, "
                               f"{fmt(ah['ai_share_pct'], '%')} of the answered ones by the AI on its own."), body)]

    rows = [["Lead cohort", "Before HAIP (measured)", "With HAIP"]]
    fb, fw = view["before"]["funnel"], view["with"]["funnel"]
    for key, label in (("enquiries", "Enquiry records"), ("leads", "New leads (phone captured)"), ("quoted", "Of them quoted"),
                       ("booked", "Of them booked")):
        rows.append([label, fb[key], fw[key]])
    mb, mw = view["before"]["missed_calls"], view["with"]["missed_calls"]
    rows += [["Missed calls", mb["missed"], mw["missed"]],
             ["Called back", f"{mb['returned']} ({fmt(mb['returned_pct'], '%')})", f"{mw['returned']} ({fmt(mw['returned_pct'], '%')})"],
             ["Median time to call back", _mins(mb["median_callback_seconds"]), _mins(mw["median_callback_seconds"])]]
    story += [Paragraph("Leads and calls", h2), _table(rows, [70 * mm, 50 * mm, 50 * mm])]

    lost = view["with"]["lost"]
    if lost["total"]:
        rows = [["Why enquiries were lost (with HAIP)", "Count"]] + [[i["label"], i["count"]] for i in lost["by_reason"]]
        story += [Spacer(1, 4), _table(rows, [120 * mm, 50 * mm])]

    rev = view.get("revenue") or {}
    if not rev.get("restricted") and rev.get("months"):
        rows = [["Month (IST)", "Bookings made", "Bookings value", "Cash collected"]]
        for m in rev["months"]:
            mark = " (go-live)" if m["month"] == rev.get("go_live_month") else ""
            rows.append([m["month"] + mark, m["bookings"], inr_text(m["booked_value"], paise=False), inr_text(m["collected"], paise=False)])
        story += [Paragraph("Revenue per month", h2), _table(rows, [45 * mm, 35 * mm, 45 * mm, 45 * mm])]

    story += [Spacer(1, 6), Paragraph(escape(f"Generated {view['generated_at'][:16].replace('T', ' ')} UTC by HAIP. Definitions: a lead is "
                                             "a person with a usable phone number; a guest turn is a guest message after our reply or "
                                             "24 h of silence; cohorts are still maturing for recent periods."), body)]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                      title=f"{brand_name} impact", author="HAIP").build(story)
    return buf.getvalue()
