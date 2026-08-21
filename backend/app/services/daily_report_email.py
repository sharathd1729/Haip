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

_SEVERITY_COLOUR = {
    "critical": "#DC2626",
    "high": "#EA580C",
    "medium": "#D97706",
    "low": "#0F766E",
    "info": "#6B7280",
}


def _e(v) -> str:
    return escape(str(v if v is not None else ""), quote=True)


def _waiting(mins: Optional[int]) -> str:
    if mins is None:
        return ""
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    return f"{hours}h" if hours < 24 else f"{hours // 24}d"


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
      </table>
    </td></tr>

    {waiting_html}
    {insights_html}

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
