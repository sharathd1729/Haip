"""Renders Yaad's "Your day at a glance" email (services/personal_digest.py builds the data) in the Mango theme.

Layout follows the NeoSapien daily summary the owner picked: a gradient hero (date, title, the day's paragraph), the
productivity card (minutes captured today, minutes saved on notes, totals so far), then Decisions taken today (bullets),
Reminders from today (numbered, "owner, date" under each, Open reminders button), Open points to resolve (hollow
bullets) and Learning of the day (a card), divided by thin rules, with a brand footer.
Email-safe on purpose: tables, inline styles, no images or SVG, a solid colour behind every gradient.
Every value is escaped; the plain-text part carries the same content.
"""

from __future__ import annotations

from datetime import date
from html import escape

INK, INK2, INK3 = "#16130C", "#5E5440", "#8A7D60"
WHITE, LINE, SOFT, MANGO, TOMATO = "#FFFFFF", "#EFE6CF", "#FFF3D1", "#FFC233", "#C8321A"
FONT = "Onest,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def _e(v) -> str:
    return escape(str(v or ""), quote=True)


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _long(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _due(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{_ordinal(d.day)} {d.strftime('%b')}, {d.year}"


def _span(minutes: int) -> list[tuple[int, str]]:
    """(number, unit) pairs: 35_483 min -> [(24, 'days'), (14, 'hrs'), (43, 'min')]; leading zeros dropped."""
    days, rest = divmod(max(0, minutes), 1440)
    hrs, mins = divmod(rest, 60)
    parts = [(days, "days" if days != 1 else "day"), (hrs, "hrs" if hrs != 1 else "hr"), (mins, "min")]
    while len(parts) > 1 and parts[0][0] == 0:
        parts.pop(0)
    return parts


def _span_text(minutes: int) -> str:
    return " ".join(f"{n} {u}" for n, u in _span(minutes))


def subject(d: dict) -> str:
    s = d["stats"]
    calls = f"{s['calls']} call{'' if s['calls'] == 1 else 's'}"
    rem = f", {s['reminders']} reminder{'' if s['reminders'] == 1 else 's'}" if s["reminders"] else ""
    day = date.fromisoformat(d["day"])
    return f"Your day, decoded: {calls}{rem} · {day.day} {day.strftime('%b')}"


def _rule() -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td style="font-size:0;line-height:0;height:36px;">&nbsp;</td></tr>'
        f'<tr><td style="border-top:1px solid {LINE};font-size:0;line-height:0;height:36px;">&nbsp;</td></tr></table>'
    )


def _heading(title: str) -> str:
    return f'<h2 style="margin:0 0 20px;text-align:center;font-size:24px;line-height:1.25;font-weight:700;letter-spacing:-.01em;color:{INK};">{_e(title)}</h2>'


def _bullets(rows: list[str], mark: str) -> str:
    body = "".join(
        f'<tr><td width="22" valign="top" style="padding:0 0 18px;font-size:16px;line-height:1.5;color:{INK};">{mark}</td>'
        f'<td valign="top" style="padding:0 0 18px;font-size:16px;line-height:1.5;color:{INK};">{_e(r)}</td></tr>'
        for r in rows
    )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{body}</table>'


def _reminders(d: dict, base: str) -> str:
    rows = []
    for i, r in enumerate(d["reminders"], 1):
        meta = ", ".join(
            [f'<em style="font-style:italic;">{_e(r["owner"])}</em>'] + ([_e(_due(r["due"]))] if r.get("due") else [])
        )
        rows.append(
            f'<tr><td width="30" valign="top" style="padding:0 0 18px;font-size:16px;line-height:1.5;color:{INK};">{i}.</td>'
            f'<td valign="top" style="padding:0 0 18px;font-size:16px;line-height:1.5;color:{INK};">{_e(r["text"])}'
            f'<div style="margin-top:4px;font-size:14px;line-height:1.45;color:{INK3};">&#8627;&nbsp; {meta}</div></td></tr>'
        )
    more = (
        f'<p style="margin:0 0 18px;font-size:14px;color:{INK3};text-align:center;">and {d["more_reminders"]} more in Yaad</p>'
        if d["more_reminders"]
        else ""
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table>{more}'
        f'<table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin-top:6px;"><tr>'
        f'<td style="background:{INK};border-radius:999px;"><a href="{_e(base + "/dashboard/me/reminders")}" '
        f'style="display:inline-block;padding:14px 36px;font-size:16px;font-weight:700;color:{MANGO};text-decoration:none;">Open reminders</a></td>'
        f"</tr></table>"
    )


def _big(minutes: int, color: str) -> str:
    return (
        f'<span style="font-size:52px;line-height:1;font-weight:800;letter-spacing:-.03em;color:{color};">{minutes:,}</span>'
        f'<span style="font-size:22px;font-weight:700;color:{color};">&nbsp;min</span>'
    )


def _span_html(minutes: int, num_color: str, unit_color: str) -> str:
    return "&nbsp;".join(
        f'<span style="font-size:24px;font-weight:800;color:{num_color};">{n}</span>'
        f'<span style="font-size:16px;color:{unit_color};">&nbsp;{u}</span>'
        for n, u in _span(minutes)
    )


def _insights(s: dict) -> str:
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{SOFT};
background-image:linear-gradient(135deg,#FFF0C2 0%,#FFF7E3 55%,#FDE7E1 100%);border-radius:24px;">
<tr><td style="padding:28px 16px 8px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td width="50%" valign="bottom" style="text-align:center;padding:0 6px;">
      {_big(s["talk_minutes"], INK)}
      <div style="margin-top:8px;font-size:16px;color:{INK2};">captured today</div>
    </td>
    <td width="50%" valign="bottom" style="text-align:center;padding:0 6px;border-left:1px solid #E3CF98;">
      <div style="font-size:14px;font-weight:600;color:{TOMATO};margin-bottom:6px;">Efficiency boost</div>
      {_big(s["saved_minutes"], TOMATO)}
      <div style="margin-top:8px;font-size:16px;color:{TOMATO};">saved in note taking</div>
    </td>
  </tr></table>
</td></tr>
<tr><td style="padding:18px 24px 0;"><div style="height:3px;background:{MANGO};border-radius:3px;font-size:0;line-height:0;">&nbsp;</div></td></tr>
<tr><td style="padding:22px 16px 6px;text-align:center;line-height:1.6;">
  {_span_html(s["total_minutes"], INK, INK2)}<span style="font-size:16px;color:{INK};">&nbsp; recorded so far</span>
</td></tr>
<tr><td style="padding:10px 16px 28px;text-align:center;line-height:2.2;">
  <span style="font-size:16px;color:{INK};">You saved&nbsp;</span>
  <span style="display:inline-block;background:{TOMATO};border-radius:999px;padding:4px 14px;line-height:1.4;">{_span_html(s["total_saved_minutes"], WHITE, "#FFE3DC")}</span>
  <span style="font-size:16px;color:{INK};">&nbsp;in note taking till date</span>
</td></tr>
</table>"""


def html(d: dict, app_url: str) -> str:
    base = app_url.rstrip("/")
    glance = (
        f'<p style="margin:28px 0 0;font-size:17px;line-height:1.75;color:{INK};">{_e(d["glance"])}</p>'
        if d["glance"]
        else ""
    )
    sections = []
    if d["decisions"]:
        sections.append(_heading("Decisions Taken Today") + _bullets(d["decisions"], "&bull;"))
    if d["reminders"]:
        sections.append(_heading("Reminders From Today") + _reminders(d, base))
    if d["open_points"]:
        sections.append(_heading("Open Points To Resolve") + _bullets(d["open_points"], "&#9702;"))
    body = "".join(f'{_rule()}<div style="padding:0 4px;">{s}</div>' for s in sections)
    learning = (
        f'{_rule()}<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SOFT};border-radius:20px;">'
        f'<tr><td style="padding:28px 28px 30px;">{_heading("Learning Of The Day")}'
        f'<p style="margin:0;font-size:16px;line-height:1.75;color:{INK};">{_e(d["learning"])}</p></td></tr></table>'
        if d["learning"]
        else ""
    )
    year = d["day"][:4]
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{_e(subject(d))}</title></head>
<body style="margin:0;padding:0;background:{WHITE};">
<div style="display:none;max-height:0;overflow:hidden;">{_e(d["glance"][:140])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{WHITE};font-family:{FONT};color:{INK};">
<tr><td align="center" style="background-color:#FFF4D6;background-image:linear-gradient(180deg,#FFE7A3 0%,#FFF4D6 45%,#FFFFFF 100%);padding:44px 20px 40px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;"><tr><td>
    <p style="margin:0;text-align:center;font-size:16px;font-weight:600;color:{INK2};">{_e(_long(d["day"]))}</p>
    <h1 style="margin:12px 0 0;text-align:center;font-size:40px;line-height:1.15;font-weight:800;letter-spacing:-.02em;color:{INK};">Your Day At A Glance</h1>
    {glance}
  </td></tr></table>
</td></tr>
<tr><td align="center" style="padding:0 20px 40px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;"><tr><td>
    {_rule()}
    {_heading("Your Productivity Insights")}
    {_insights(d["stats"])}
    {body}
    {learning}
    {_rule()}
    <table role="presentation" cellpadding="0" cellspacing="0" align="center"><tr>
      <td style="background:{INK};color:{MANGO};font-size:20px;font-weight:800;padding:7px 16px;border-radius:12px;letter-spacing:-.03em;">yaad</td>
    </tr></table>
    <p style="margin:18px 0 0;text-align:center;font-size:13px;line-height:1.6;color:{INK3};">&copy;{year} Yaad by HAIP. Summaries are written by AI from your
    call recordings and can miss things.<br>This is an automated message. Replies to this email will not be received.</p>
  </td></tr></table>
</td></tr>
</table>
</body></html>"""


def text(d: dict, app_url: str) -> str:
    base = app_url.rstrip("/")
    s = d["stats"]
    out = [_long(d["day"]), "", "YOUR DAY AT A GLANCE"]
    out += [d["glance"], ""] if d["glance"] else [""]
    out += [
        "YOUR PRODUCTIVITY INSIGHTS",
        f"{s['talk_minutes']} min captured today · {s['saved_minutes']} min saved in note taking",
        f"{_span_text(s['total_minutes'])} recorded so far · you saved {_span_text(s['total_saved_minutes'])} in note taking till date",
        "",
    ]
    if d["decisions"]:
        out += ["DECISIONS TAKEN TODAY", *[f"- {x}" for x in d["decisions"]], ""]
    if d["reminders"]:
        out.append("REMINDERS FROM TODAY")
        for i, r in enumerate(d["reminders"], 1):
            out.append(f"{i}. {r['text']} ({r['owner']}" + (f", {_due(r['due'])})" if r.get("due") else ")"))
        if d["more_reminders"]:
            out.append(f"and {d['more_reminders']} more in Yaad")
        out += [f"Open reminders: {base}/dashboard/me/reminders", ""]
    if d["open_points"]:
        out += ["OPEN POINTS TO RESOLVE", *[f"- {x}" for x in d["open_points"]], ""]
    if d["learning"]:
        out += ["LEARNING OF THE DAY", d["learning"], ""]
    out += ["This is an automated message from Yaad. Replies to this email will not be received."]
    return "\n".join(out)
