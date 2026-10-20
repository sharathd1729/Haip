"""Render the owner's daily brief (owner_brief_service.build) as an email: subject, HTML and plain text.

Option C (owner pick 21 Oct 2026): a short paragraph, then "Today" with up to three people to call, then two links. One fluid
column (max 560 px, readable on a phone), inline styles only (email clients drop <style>), everything escaped.
"""
from __future__ import annotations

from html import escape

BRAND = "#1E7A5A"
INK = "#1F2A24"
MUTED = "#5F6B66"
RULE = "#E3E7E4"
CANVAS = "#F6F5F1"


def subject(brief: dict, tenant_name: str) -> str:
    n = brief["numbers"]
    label = "morning brief" if brief["kind"] == "morning" else "evening check"
    bits = [f"{n['leads']} new lead{'s' if n['leads'] != 1 else ''}"]
    if n["bookings"]:
        bits.append(f"{n['bookings']} booked")
    calls = sum(1 for t in brief["todos"] if t["text"].startswith("Call"))
    if calls:
        bits.append(f"{calls} to call")
    return f"{tenant_name} {label} · {brief['day_label']}: " + ", ".join(bits)


def text(brief: dict, tenant_name: str) -> str:
    lines = [f"{tenant_name} · {brief['period']} ({brief['day_label']})", "", " ".join(brief["sentences"]), ""]
    if brief["todos"]:
        lines.append("Today")
        lines += [f"- {t['text']}  {t['url']}" for t in brief["todos"]]
        lines.append("")
    lines += [f"Open My day: {brief['my_day_url']}", f"Dashboard: {brief['dashboard_url']}", "",
              "You get this because you own or manage this workspace. Turn it off in Settings > Notifications."]
    return "\n".join(lines)


def html(brief: dict, tenant_name: str) -> str:
    title = "Morning brief" if brief["kind"] == "morning" else "Evening check"
    para = escape(" ".join(brief["sentences"]))
    todo_rows = "".join(
        f'<tr><td style="padding:10px 0;border-top:1px solid {RULE};font-size:15px;line-height:1.45;color:{INK}">'
        f'<a href="{escape(t["url"], quote=True)}" style="color:{INK};text-decoration:none">{escape(t["text"])}</a>'
        f'<span style="color:{BRAND}"> &rsaquo;</span></td></tr>'
        for t in brief["todos"])
    today = (f'<p style="margin:22px 0 4px;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{MUTED}">Today</p>'
             f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{todo_rows}</table>') if todo_rows else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:{CANVAS};font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CANVAS}"><tr><td align="center" style="padding:20px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:14px">
<tr><td style="padding:24px 22px">
<p style="margin:0;font-size:13px;color:{MUTED}">{escape(tenant_name)} · {escape(brief['period'])}, {escape(brief['day_label'])}</p>
<h1 style="margin:4px 0 14px;font-size:22px;line-height:1.25;color:{INK}">{escape(title)}</h1>
<p style="margin:0;font-size:16px;line-height:1.6;color:{INK}">{para}</p>
{today}
<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:22px"><tr>
<td style="background:{BRAND};border-radius:10px"><a href="{escape(brief['my_day_url'], quote=True)}" style="display:inline-block;padding:12px 18px;font-size:15px;font-weight:700;color:#ffffff;text-decoration:none">Open My day</a></td>
<td style="padding-left:14px"><a href="{escape(brief['dashboard_url'], quote=True)}" style="font-size:14px;color:{BRAND}">Dashboard</a></td>
</tr></table>
</td></tr></table>
<p style="max-width:560px;margin:14px auto 0;font-size:12px;line-height:1.5;color:{MUTED}">Leads are people who shared a phone number. Times and days are IST.
You get this because you own or manage this workspace; turn it off in Settings &rsaquo; Notifications.</p>
</td></tr></table></body></html>"""
