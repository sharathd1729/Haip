"""One Ask Yaad answer as an EDITABLE PDF (owner, 15 Nov): the answer sits in fillable text boxes (AcroForm), so the
person can change the wording in any PDF reader before sending it on; the question, date and sources are printed.

reportlab, built-in Helvetica (Latin-1 only: ops_trip_report._latin). A long answer continues in a new box on the next
page. Lines are pre-wrapped to the box width, so what you see is what the reader shows before any edit.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from app.services.ops_trip_report import _latin

IST = ZoneInfo("Asia/Kolkata")
MARGIN = 18 * mm
SIZE = 10.5
LEAD = SIZE * 1.45


def _plain(text: str) -> str:
    """WhatsApp *bold* markers off; "* " list lines become bullets."""
    out = []
    for line in text.split("\n"):
        m = re.match(r"^\s*[*•-]\s+(.*)$", line)
        line = f"- {m.group(1)}" if m else line
        out.append(re.sub(r"\*([^*\n]+)\*", r"\1", line))
    return "\n".join(out)


def _wrap(text: str, width: float, font: str = "Helvetica", size: float = SIZE) -> list[str]:
    lines: list[str] = []
    for para in _latin(text).split("\n"):
        lines += simpleSplit(para, font, size, width) or [""]
    return lines


def render(*, question: str, answer: str, sources: list[dict], asked_at: str | None, owner: str = "") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(_latin(question[:80]))
    c.setAuthor("Yaad")
    w, h = A4
    width = w - 2 * MARGIN
    y = h - MARGIN

    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, y - 4, "Ask Yaad")
    y -= 24
    when = ""
    if asked_at:
        try:
            when = datetime.fromisoformat(asked_at).astimezone(IST).strftime("%d %b %Y, %I:%M %p")
        except ValueError:
            when = ""
    c.setFont("Helvetica", 9)
    c.setFillGray(0.4)
    c.drawString(MARGIN, y, _latin(" · ".join(x for x in (owner, when, "You can edit the answer below") if x)))
    c.setFillGray(0)
    y -= 18
    c.setFont("Helvetica-Bold", 12)
    for line in _wrap(question, width, "Helvetica-Bold", 12):
        c.drawString(MARGIN, y, line)
        y -= 16
    y -= 6

    lines = _wrap(_plain(answer), width - 8)
    box = 0
    while lines:
        room = int((y - MARGIN - (90 if box == 0 else 0)) // LEAD)
        if room < 3:
            c.showPage()
            y = h - MARGIN
            continue
        chunk, lines = lines[:room], lines[room:]
        height = len(chunk) * LEAD + 8
        box += 1
        c.acroForm.textfield(
            name=f"answer_{box}",
            tooltip="Answer (you can edit this)",
            value="\n".join(chunk),
            x=MARGIN,
            y=y - height,
            width=width,
            height=height,
            fontName="Helvetica",
            fontSize=SIZE,
            borderWidth=0,
            fillColor=None,
            textColor=None,
            fieldFlags="multiline",
            forceBorder=False,
        )
        y -= height + 10

    if sources:
        if y < MARGIN + 60:
            c.showPage()
            y = h - MARGIN
        c.setFont("Helvetica-Bold", 11)
        c.drawString(MARGIN, y, "Sources")
        y -= 16
        for s in sources:
            head = f"[{s.get('n')}] {s.get('contact') or ''} - {s.get('title') or 'Call'}"
            try:
                head += " - " + datetime.fromisoformat(s["at"]).astimezone(IST).strftime("%d %b %Y")
            except (KeyError, TypeError, ValueError):
                pass
            rows = _wrap(head, width, "Helvetica-Bold", 9.5)
            if s.get("quote"):
                rows += _wrap(f'"{s["quote"]}"', width - 10, "Helvetica-Oblique", 9)
            for i, row in enumerate(rows):
                if y < MARGIN:
                    c.showPage()
                    y = h - MARGIN
                bold = i < len(_wrap(head, width, "Helvetica-Bold", 9.5))
                c.setFont("Helvetica-Bold" if bold else "Helvetica-Oblique", 9.5 if bold else 9)
                c.drawString(MARGIN + (0 if bold else 10), y, row)
                y -= 12.5
            y -= 4
    c.setFont("Helvetica", 8)
    c.setFillGray(0.5)
    c.drawString(MARGIN, MARGIN / 2, "Made with Yaad, from your own calls")
    c.save()
    return buf.getvalue()
