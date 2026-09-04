"""HTML rendering for the daily owner report.

Table-based layout with inline styles on purpose: Gmail strips <style>
blocks, Outlook's renderer is Word-based and ignores flexbox/grid outright.
Everything here is deliberately 2005-era markup because that is what
actually survives an inbox.

All interpolated values are escaped -- guest names arrive from Instagram
and WhatsApp and are entirely attacker-controlled.
"""

from __future__ import annotations

from html import escape
from typing import Optional

BRAND = "#0F766E"
INK = "#111827"
MUTED = "#6B7280"
LINE = "#E5E7EB"
IRIS = "#5B5BCE"
IRIS_BG = "#F1F0FB"
IRIS_INK = "#4A4AB0"

_SEVERITY_COLOUR = {
    "critical": "#DC2626",
    "high": "#EA580C",
    "medium": "#D97706",
    "low": "#0F766E",
    "info": "#6B7280",
}

# Detailed per-lead report: status badge + calls-disposition colours.
_STATUS_COLOUR = {
    "booked": ("#0F7A56", "#E8F5EE"),
    "quoted": ("#1D5FA8", "#E9F1FB"),
    "progress": ("#8A6D00", "#FCF6DC"),
    "lost": ("#B3261E", "#FBEAE9"),
}
_STATUS_LABEL = {"booked": "Booked", "quoted": "Quoted", "lost": "Lost", "progress": "Awaiting reply"}
_STATUS_PRIORITY = {"booked": 0, "lost": 0, "quoted": 1, "progress": 2}
_MAX_CONDENSED_LEADS = 2

_CHANNEL_COLOUR = {"whatsapp": "#25D366", "instagram": "#C13584", "call": BRAND, "voice": BRAND, "webchat": MUTED, "email": MUTED}


def _e(v) -> str:
    return escape(str(v if v is not None else ""), quote=True)


def _fmt_amount(v) -> str:
    return f"₹{v:,.0f}"


def _status_badge(status: str) -> str:
    fg, bg = _STATUS_COLOUR.get(status, (MUTED, "#F3F4F6"))
    label = _STATUS_LABEL.get(status, status.replace("_", " ").title())
    return (
        f'<span style="display:inline-block;font:700 10px -apple-system,Segoe UI,Roboto,sans-serif;'
        f'color:{fg};background:{bg};padding:3px 8px;border-radius:999px;text-transform:uppercase">{_e(label)}</span>'
    )


def _lead_meta_parts(lead: dict) -> list[str]:
    parts = []
    if lead.get("route_mentioned"):
        parts.append(lead["route_mentioned"])
    if lead.get("guest_count"):
        parts.append(lead["guest_count"])
    if lead.get("quoted_amount") is not None:
        parts.append(f"{_fmt_amount(lead['quoted_amount'])} quoted")
    return parts


def _lead_card_html(lead: dict, dashboard_url: str) -> str:
    """Full per-lead card -- the agent's own email. Detailed per-lead
    report: route/guests/price/special-request grid, an upsell callout if
    one was offered, and the synthesized ai_lead_analysis paragraph."""
    fields = [
        ("Route", lead.get("route_mentioned") or "—"),
        ("Guests", lead.get("guest_count") or "—"),
        ("Price quoted", _fmt_amount(lead["quoted_amount"]) if lead.get("quoted_amount") is not None else "Not yet quoted"),
        ("Special request", lead.get("special_requests") or "None mentioned"),
    ]
    grid_rows = []
    for i in range(0, len(fields), 2):
        cells = "".join(
            f'''<td width="50%" style="padding:6px 8px 0 0;vertical-align:top">
              <div style="font:700 9.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.05em">{_e(k)}</div>
              <div style="font:12.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK};margin-top:1px">{_e(v)}</div>
            </td>'''
            for k, v in fields[i:i + 2]
        )
        grid_rows.append(f"<tr>{cells}</tr>")

    upsell_html = ""
    if lead.get("upsell_offered"):
        accepted = lead.get("upsell_accepted")
        bg, fg = ("#E8F5EE", "#0F7A56") if accepted else ("#FCF6DC", "#6B5400")
        verb = "accepted" if accepted else ("declined" if accepted is False else "offered")
        upsell_html = (
            f'<div style="margin-top:8px;padding:8px 10px;border-radius:7px;background:{bg};'
            f'font:11.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{fg}">'
            f'<b>Upsell {_e(verb)}:</b> {_e(lead["upsell_offered"])}</div>'
        )

    analysis_html = ""
    if lead.get("ai_lead_analysis"):
        analysis_html = (
            f'<div style="margin-top:8px;padding:9px 11px;border-radius:7px;background:{IRIS_BG};border-left:3px solid {IRIS}">'
            f'<div style="font:700 9.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{IRIS_INK};'
            f'text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px">AI analysis</div>'
            f'<div style="font:12.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK};font-style:italic">{_e(lead["ai_lead_analysis"])}</div>'
            f'</div>'
        )

    return f"""
    <tr><td style="padding:0 0 10px">
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {LINE};border-radius:10px">
        <tr><td style="padding:13px 14px 14px">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td>
              <div style="font:700 13.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK}">{_e(lead['guest_name'])}</div>
              <div style="font:11px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:1px">
                {_e(lead['channel'])}{f" · {_e(lead['intent'])}" if lead.get('intent') else ""}
                {f' · <a href="{_profile_link(dashboard_url, lead.get("guest_id"))}" style="color:{BRAND};font-weight:700;text-decoration:none">Profile 360 →</a>' if lead.get('guest_id') else ''}
              </div>
            </td>
            <td align="right" valign="top">{_status_badge(lead['status'])}</td>
          </tr></table>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:11px;padding-top:11px;border-top:1px dashed {LINE}">{"".join(grid_rows)}</table>
          {upsell_html}
          {analysis_html}
        </td></tr>
      </table>
    </td></tr>"""


def _lead_condensed_html(lead: dict) -> str:
    """One-line lead row -- the owner email's per-agent section, top 2-3
    most decision-relevant leads only (see _STATUS_PRIORITY)."""
    meta_line = " · ".join(_e(p) for p in _lead_meta_parts(lead))
    analysis_html = (
        f'<div style="font:11px -apple-system,Segoe UI,Roboto,sans-serif;color:{IRIS_INK};font-style:italic;margin-top:3px">{_e(lead["ai_lead_analysis"])}</div>'
        if lead.get("ai_lead_analysis") else ""
    )
    return f"""
      <tr><td style="padding:10px 0;border-bottom:1px solid {LINE}">
        <div style="font:700 12.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK}">{_e(lead['guest_name'])} {_status_badge(lead['status'])}</div>
        {f'<div style="font:11.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">{meta_line}</div>' if meta_line else ''}
        {analysis_html}
      </td></tr>"""


def _channel_mix_html(by_channel: dict) -> str:
    if not by_channel:
        return ""
    total = sum(by_channel.values()) or 1
    items = sorted(by_channel.items(), key=lambda kv: -kv[1])
    bar_cells = "".join(
        f'<td width="{max(round(v / total * 100), 1)}%" style="background:{_CHANNEL_COLOUR.get(k, MUTED)};height:10px;font-size:0;line-height:0">&nbsp;</td>'
        for k, v in items
    )
    legend = "&nbsp;&nbsp;&nbsp;".join(
        f'<span style="display:inline-block;width:8px;height:8px;background:{_CHANNEL_COLOUR.get(k, MUTED)};'
        f'border-radius:2px;margin-right:4px"></span>{_e(k.title())} · {v}'
        for k, v in items
    )
    return f"""
    <tr><td style="padding:20px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Channel mix</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px;border-radius:999px;overflow:hidden"><tr>{bar_cells}</tr></table>
      <div style="font:11px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:8px">{legend}</div>
    </td></tr>"""


def _calls_detail_html(report: dict) -> str:
    by_disp = report.get("calls_by_disposition") or {}
    notable = report.get("notable_calls") or []
    if not by_disp:
        return ""
    chips = "".join(
        f'<span style="display:inline-block;margin:0 6px 6px 0;font:700 11px -apple-system,Segoe UI,Roboto,sans-serif;'
        f'color:{_STATUS_COLOUR.get(d, (MUTED, "#F3F4F6"))[0]};background:{_STATUS_COLOUR.get(d, (MUTED, "#F3F4F6"))[1]};'
        f'padding:5px 11px;border-radius:999px">{_e(d.replace("_", " ").title())} {n}</span>'
        for d, n in by_disp.items()
    )
    notable_rows = "".join(f"""
      <tr><td style="padding:8px 0;border-bottom:1px solid {LINE}">
        <span style="display:inline-block;font:700 10px -apple-system,Segoe UI,Roboto,sans-serif;color:#fff;background:{MUTED};padding:2px 6px;border-radius:3px;text-transform:uppercase">{_e(c['disposition'])}</span>
        <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">{_e(c['summary']) or 'No AI summary available.'}</div>
      </td></tr>""" for c in notable)
    return f"""
    <tr><td style="padding:20px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Calls</div>
      <div style="margin-top:8px">{chips}</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:4px">{notable_rows}</table>
    </td></tr>"""


def _lost_today_html(lost: dict) -> str:
    if not lost or not lost.get("count"):
        return ""
    reasons_str = ", ".join(f"{r['reason'].replace('_', ' ')} ({r['count']})" for r in lost["reasons"])
    example = (lost.get("examples") or [None])[0]
    example_str = ""
    if example:
        example_str = f" {_e(example['guest_name'])}"
        if example.get("route_mentioned"):
            example_str += f"'s {_e(example['route_mentioned'])} trip"
        if example.get("quoted_amount") is not None:
            example_str += f" objected to the {_fmt_amount(example['quoted_amount'])} quote."
        else:
            example_str += "."
    return f"""
    <tr><td style="padding:20px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Lost today</div>
      <div style="margin-top:8px;padding:10px 12px;border-radius:8px;background:#FBEAE9;font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK};line-height:1.5">
        <b style="color:#B3261E">{lost['count']} lead{'s' if lost['count'] != 1 else ''} lost</b> — {_e(reasons_str)}.{example_str}
      </div>
    </td></tr>"""


def _leads_summary_html(block: dict) -> str:
    if not block.get("leads_summary"):
        return ""
    return f"""
    <tr><td style="padding:20px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Leads summary</div>
      <div style="margin-top:8px;padding:12px 14px;border-radius:10px;background:#FBFAF6;border:1px solid {LINE};font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK};line-height:1.6">{_e(block['leads_summary'])}</div>
    </td></tr>"""


def _feedback_html(block: dict) -> str:
    items = block.get("leads_feedback") or []
    if not items:
        return ""
    rows = []
    for item in items:
        good = item.get("type") == "good"
        bg = "#0F7A56" if good else "#8A6D00"
        icon = "✓" if good else "→"
        rows.append(f"""
          <tr><td style="padding:8px 0;border-bottom:1px solid {LINE}">
            <table cellpadding="0" cellspacing="0"><tr>
              <td width="24" valign="top"><span style="display:inline-block;width:18px;height:18px;border-radius:50%;background:{bg};color:#fff;font:800 10px -apple-system,Segoe UI,Roboto,sans-serif;text-align:center;line-height:18px">{icon}</span></td>
              <td style="font:12.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK};line-height:1.5;padding-left:6px">{_e(item['text'])}</td>
            </tr></table>
          </td></tr>""")
    return f"""
    <tr><td style="padding:20px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Feedback</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">{"".join(rows)}</table>
    </td></tr>"""


def _waiting(mins: Optional[int]) -> str:
    if mins is None:
        return ""
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    return f"{hours}h" if hours < 24 else f"{hours // 24}d"


def _profile_link(dashboard_url: str, guest_id: Optional[str]) -> str:
    """Profile 360 deep link for one guest, or '' when there's no guest_id
    to link to (e.g. a lead whose identity never resolved to a Guest row)."""
    if not guest_id:
        return ""
    return f'{_e(dashboard_url)}/guests/{_e(guest_id)}'


def _phone_declines_html(items: list[dict], dashboard_url: str) -> str:
    """Phone-decline alert plan: guests who explicitly refused to share a
    phone number and are still waiting on a human reply in the DM (see
    concierge_draft.py's _maybe_alert_phone_decline) -- a standing backlog,
    not scoped to this report's day/window, same reasoning as the
    still-waiting section above."""
    if not items:
        return ""
    rows = "".join(f"""
      <tr><td style="padding:8px 0;border-bottom:1px solid {LINE}">
        <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:#B3261E">{_e(i['guest_name'])}</div>
        <div style="font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">
          Declined to share a phone number, asking to be helped in the DM directly.
          {f'<a href="{_profile_link(dashboard_url, i["guest_id"])}" style="color:{BRAND};font-weight:700;text-decoration:none">View Profile 360 →</a>' if i.get('guest_id') else ''}
        </div>
      </td></tr>""" for i in items)
    return f"""
    <tr><td style="padding:20px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Declined to share a phone number &middot; {len(items)}</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">{rows}</table>
    </td></tr>"""


def _stat(label: str, value, *, accent: str = INK, note: str = "") -> str:
    note_html = (
        f'<div style="font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">{_e(note)}</div>'
        if note else ""
    )
    return f"""
      <td width="33%" style="padding:12px 8px;vertical-align:top">
        <div style="font:700 26px -apple-system,Segoe UI,Roboto,sans-serif;color:{accent}">{_e(value)}</div>
        <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED}">{_e(label)}</div>
        {note_html}
      </td>"""


def render_daily_report(report: dict, *, tenant_name: str, dashboard_url: str) -> str:
    m = report["metrics"]
    date = report["date"]
    is_evening = report.get("kind") == "evening"
    # The two sends answer different questions, so the framing differs even
    # though the underlying queries are shared.
    header_note = (
        f"Today so far · {date}" if is_evening else f"Yesterday · {date}"
    )
    waiting_heading = (
        "Came in today, still unanswered" if is_evening
        else f"Still waiting (last {report.get('backlog_days', 5)} days)"
    )
    volume_heading = "Today so far" if is_evening else "Yesterday"

    channel_note = ", ".join(
        f"{v} {k}" for k, v in sorted(m["by_channel"].items(), key=lambda kv: -kv[1])
    ) or "no messages"

    # ── The part that needs action, first ────────────────────────────────
    attention_rows = []
    if m["awaiting_reply"]:
        attention_rows.append((
            f"{m['awaiting_reply']} conversations waiting on a reply",
            ("These came in today and nobody has replied yet."
             if is_evening else
             f"Unanswered from the last {report.get('backlog_days', 5)} days."),
            "#DC2626",
        ))
    if m["missed_not_returned"]:
        attention_rows.append((
            f"{m['missed_not_returned']} missed calls not returned",
            "Inbound calls with no talk time and no call-back logged.",
            "#EA580C",
        ))
    if not attention_rows:
        attention_rows.append((
            "Nothing outstanding",
            "Every conversation in this window has been answered.",
            BRAND,
        ))

    attention_html = "".join(f"""
      <tr>
        <td style="padding:10px 14px;border-left:3px solid {c};background:#FAFAFA">
          <div style="font:600 15px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK}">{_e(t)}</div>
          <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">{_e(s)}</div>
        </td>
      </tr>
      <tr><td height="8"></td></tr>""" for t, s, c in attention_rows)

    # ── Longest waiting, by name ─────────────────────────────────────────
    waiting_html = ""
    if report["top_waiting"]:
        rows = "".join(f"""
          <tr>
            <td style="padding:8px 0;border-bottom:1px solid {LINE}">
              <div style="font:600 14px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK}">
                {_e(w['name'])}
                <span style="font-weight:400;color:{MUTED};font-size:12px">
                  &nbsp;{_e(w.get('channel') or '')} · waiting {_e(_waiting(w.get('waiting_minutes')))}
                </span>
              </div>
              <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">{_e(w['message'])}</div>
              {'' if w['has_contact'] else f'<div style="font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:#B45309;margin-top:2px">No contact details captured</div>'}
              {f'<a href="{_profile_link(dashboard_url, w.get("guest_id"))}" style="font:11px -apple-system,Segoe UI,Roboto,sans-serif;color:{BRAND};font-weight:700;text-decoration:none">View Profile 360 →</a>' if w.get('guest_id') else ''}
            </td>
          </tr>""" for w in report["top_waiting"])
        waiting_html = f"""
        <tr><td style="padding:20px 24px 0">
          <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">{_e(waiting_heading)}</div>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">{rows}</table>
        </td></tr>"""

    # ── AI insights ──────────────────────────────────────────────────────
    insights_html = ""
    if report["insights"]:
        items = "".join(f"""
          <tr>
            <td style="padding:8px 0;border-bottom:1px solid {LINE}">
              <span style="display:inline-block;font:700 10px -apple-system,Segoe UI,Roboto,sans-serif;color:#fff;background:{_SEVERITY_COLOUR.get(i['severity'], MUTED)};padding:2px 6px;border-radius:3px;text-transform:uppercase">{_e(i['severity'])}</span>
              <div style="font:600 14px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK};margin-top:4px">{_e(i['title'])}</div>
              {f'<div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">{_e(i["body"])}</div>' if i.get('body') else ''}
            </td>
          </tr>""" for i in report["insights"])
        insights_html = f"""
        <tr><td style="padding:20px 24px 0">
          <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">AI insights</div>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">{items}</table>
        </td></tr>"""

    # ── Team performance, one block per agent ────────────────────────────
    team_html = ""
    if report.get("by_agent"):
        blocks = []
        for a in report["by_agent"]:
            sc = a["scorecard"]
            calls_rows = "".join(f"""
              <tr>
                <td style="padding:6px 0;border-bottom:1px solid {LINE}">
                  <span style="display:inline-block;font:700 10px -apple-system,Segoe UI,Roboto,sans-serif;color:#fff;background:{MUTED};padding:2px 6px;border-radius:3px;text-transform:uppercase">{_e(c['disposition'])}</span>
                  <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">{_e(c['summary']) or 'No AI summary available.'}</div>
                </td>
              </tr>""" for c in a["notable_calls"])
            narrative_html = (
                f'<div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK};margin-top:8px;line-height:1.5">{_e(a["narrative"])}</div>'
                if a.get("narrative") else ""
            )

            # Detailed per-lead report: top 2 most decision-relevant leads
            # (booked/lost first) condensed, with a "View all" link into the
            # in-app Lead Activity page for the rest -- keeps a multi-agent
            # owner email from ballooning with every lead's full card.
            leads = a.get("leads") or []
            leads_html = ""
            if leads:
                top_leads = sorted(leads, key=lambda l: _STATUS_PRIORITY.get(l["status"], 3))[:_MAX_CONDENSED_LEADS]
                lead_rows = "".join(_lead_condensed_html(l) for l in top_leads)
                view_all = ""
                if len(leads) > _MAX_CONDENSED_LEADS:
                    agent_id = a.get("agent_id")
                    qs = f"?agent_id={agent_id}&date={date}" if agent_id else f"?date={date}"
                    view_all = (
                        f'<tr><td style="padding-top:4px"><a href="{_e(dashboard_url)}/leads-activity{_e(qs)}" '
                        f'style="display:block;text-align:center;padding:9px;font:700 11.5px -apple-system,Segoe UI,Roboto,sans-serif;'
                        f'color:{BRAND};text-decoration:none;border:1.5px dashed {LINE};border-radius:8px">View all {len(leads)} leads →</a></td></tr>'
                    )
                leads_html = f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px">{lead_rows}{view_all}</table>'

            blocks.append(f"""
            <tr><td style="padding:16px 0 0">
              <div style="font:600 14px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK}">{_e(a['agent_name'])}</div>
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">
                <tr>
                  {_stat("Leads", sc['leads_handled'])}
                  {_stat("Calls", f"{sc['calls_answered']}/{sc['calls_answered'] + sc['calls_missed']}", note="answered/total")}
                  {_stat("Conversions", sc['conversions'], accent=BRAND)}
                </tr>
              </table>
              {narrative_html}
              {leads_html}
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px">{calls_rows}</table>
            </td></tr>""")
        team_html = f"""
        <tr><td style="padding:20px 24px 0">
          <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Team performance</div>
          <table width="100%" cellpadding="0" cellspacing="0">{"".join(blocks)}</table>
        </td></tr>"""

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#F3F4F6">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F3F4F6;padding:24px 12px">
<tr><td align="center">
  <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;max-width:600px">

    <tr><td style="background:{BRAND};padding:20px 24px">
      <div style="font:700 18px -apple-system,Segoe UI,Roboto,sans-serif;color:#fff">{_e(tenant_name)}</div>
      <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:#CCFBF1;margin-top:2px">{_e(header_note)}</div>
    </td></tr>

    <tr><td style="padding:20px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Needs attention</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px">{attention_html}</table>
    </td></tr>

    <tr><td style="padding:8px 16px 0">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          {_stat("Messages in", m["dms_in"], note=channel_note)}
          {_stat("Replies sent", m["replies_out"])}
          {_stat("Shared phone/email", m["shared_details"], accent=BRAND)}
        </tr>
        <tr>
          {_stat("New leads", m["new_leads"])}
          {_stat("Qualified", m["qualified_leads"], accent=BRAND)}
          {_stat("Calls", m["calls_total"], note=f"{m['calls_missed']} missed")}
        </tr>
        <tr>
          {_stat("Bookings", m["bookings"], accent=BRAND)}
          {_stat("Revenue", _fmt_amount(m["revenue"]), accent=BRAND)}
          {_stat("Conversion rate", f"{m['conversion_rate']}%")}
        </tr>
      </table>
    </td></tr>

    {_channel_mix_html(m["by_channel"])}
    {_calls_detail_html(report)}
    {_lost_today_html(report.get("lost_today"))}
    {waiting_html}
    {_phone_declines_html(report.get("phone_declines") or [], dashboard_url)}
    {insights_html}
    {team_html}

    <tr><td style="padding:24px" align="center">
      <a href="{_e(dashboard_url)}" style="display:inline-block;background:{BRAND};color:#fff;text-decoration:none;font:600 14px -apple-system,Segoe UI,Roboto,sans-serif;padding:11px 22px;border-radius:8px">Open HAIP</a>
    </td></tr>

    <tr><td style="padding:0 24px 22px" align="center">
      <div style="font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED}">
        {_e(volume_heading)} covers {_e(date)} (IST). Waiting and missed-call figures are current.
      </div>
    </td></tr>

  </table>
</td></tr></table>
</body></html>"""


def render_agent_report_html(block: dict, *, tenant_name: str, dashboard_url: str) -> str:
    """One agent's own end-of-day report -- same plain-table style as
    render_daily_report, personal framing ("your day") instead of the
    owner's team-wide framing. `block` is daily_report_service.
    build_agent_daily_report()'s return shape (scorecard/notable_calls/
    narrative/date/agent_name)."""
    sc = block["scorecard"]
    narrative_html = (
        f'<div style="font:14px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK};margin-top:10px;line-height:1.6">{_e(block["narrative"])}</div>'
        if block.get("narrative") else ""
    )
    calls_rows = "".join(f"""
      <tr>
        <td style="padding:8px 0;border-bottom:1px solid {LINE}">
          <span style="display:inline-block;font:700 10px -apple-system,Segoe UI,Roboto,sans-serif;color:#fff;background:{MUTED};padding:2px 6px;border-radius:3px;text-transform:uppercase">{_e(c['disposition'])}</span>
          <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:2px">{_e(c['summary']) or 'No AI summary available.'}</div>
        </td>
      </tr>""" for c in block["notable_calls"])
    calls_html = f"""
    <tr><td style="padding:20px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Your notable calls today</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">{calls_rows}</table>
    </td></tr>""" if block["notable_calls"] else ""

    # Detailed per-lead report: every lead this agent worked on today, full
    # card each (unlike the owner email's condensed top-2), plus an
    # aggregate leads-summary paragraph and coaching feedback beneath it.
    leads = block.get("leads") or []
    leads_html = ""
    if leads:
        cards = "".join(_lead_card_html(l, dashboard_url) for l in leads)
        leads_html = f"""
        <tr><td style="padding:20px 24px 0">
          <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Lead breakdown</div>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px">{cards}</table>
        </td></tr>"""
    leads_summary_html = _leads_summary_html(block)
    feedback_html = _feedback_html(block)

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#F3F4F6">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F3F4F6;padding:24px 12px">
<tr><td align="center">
  <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;max-width:600px">

    <tr><td style="background:{BRAND};padding:20px 24px">
      <div style="font:700 18px -apple-system,Segoe UI,Roboto,sans-serif;color:#fff">Your day, {_e(block['agent_name'].split()[0] if block['agent_name'] else '')}</div>
      <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:#CCFBF1;margin-top:2px">{_e(tenant_name)} · {_e(block['date'])}</div>
    </td></tr>

    <tr><td style="padding:20px 24px 0">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          {_stat("Leads handled", sc['leads_handled'])}
          {_stat("Calls answered", f"{sc['calls_answered']}/{sc['calls_answered'] + sc['calls_missed']}")}
          {_stat("Conversions", sc['conversions'], accent=BRAND)}
        </tr>
        <tr>
          {_stat("Avg response", f"{int(sc['avg_response_seconds'])}s" if sc['avg_response_seconds'] else "—")}
          {_stat("Follow-ups", f"{sc['followups_completed']}/{sc['followups_total']}", note=f"{sc['followups_overdue']} overdue" if sc['followups_overdue'] else "")}
        </tr>
      </table>
      {narrative_html}
    </td></tr>

    {leads_html}
    {leads_summary_html}
    {feedback_html}
    {calls_html}
    {_phone_declines_html(block.get("phone_declines") or [], dashboard_url)}

    <tr><td style="padding:24px" align="center">
      <a href="{_e(dashboard_url)}" style="display:inline-block;background:{BRAND};color:#fff;text-decoration:none;font:600 14px -apple-system,Segoe UI,Roboto,sans-serif;padding:11px 22px;border-radius:8px">Open HAIP</a>
    </td></tr>

  </table>
</td></tr></table>
</body></html>"""


def render_agent_report_subject(block: dict, tenant_name: str) -> str:
    sc = block["scorecard"]
    first_name = block["agent_name"].split()[0] if block["agent_name"] else "there"
    return f"{first_name}, your day at {tenant_name}: {sc['leads_handled']} leads, {sc['calls_answered']} calls answered"


def render_subject(report: dict, tenant_name: str) -> str:
    m = report["metrics"]
    evening = report.get("kind") == "evening"
    lead_in = "Before you close up" if evening else "Good morning"
    if m["awaiting_reply"]:
        return (
            f"{lead_in}, {tenant_name}: {m['awaiting_reply']} waiting on a reply"
            f" · {m['dms_in']} messages"
        )
    return (
        f"{lead_in}, {tenant_name}: {m['dms_in']} messages, {m['new_leads']} new leads"
    )
