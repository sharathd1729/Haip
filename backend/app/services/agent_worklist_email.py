"""HTML rendering for the agent worklist reminder email.

Same plain-table, inline-style conventions as daily_report_email.py (Gmail
strips <style> blocks, Outlook's renderer ignores flexbox/grid) -- built on
two of worklist_service's own section queries (awaiting_reply,
overdue_followups), not a new query.

Deliberately NOT built on the full build_worklist(): three of its five
sections (missed_calls, shared_contact_details, new_dms) have no
scope_user_id filter at all -- they're tenant-wide by design, meant for the
owner's/whole-team's worklist view. Reusing build_worklist() wholesale for a
PER-AGENT email would silently show every agent the same tenant-wide
missed-calls/shared-details/new-DMs data regardless of who it's actually
assigned to. Only the two sections worklist_service itself scopes to one
agent belong in a personal reminder."""

from __future__ import annotations

from html import escape
from typing import Optional

BRAND = "#0F766E"
INK = "#111827"
MUTED = "#6B7280"
LINE = "#E5E7EB"
AMBER_BG = "#FEF3C7"
AMBER_INK = "#92400E"

# Row cap per section -- keeps the email short. The "View all" link covers
# the rest; the in-app worklist has no such cap.
_MAX_ROWS = 5

_SECTION_TITLES = {
    "awaiting_reply": "Waiting on your reply",
    "overdue_followups": "Overdue follow-ups",
}
_SECTION_ORDER = ("awaiting_reply", "overdue_followups")


def _e(v) -> str:
    return escape(str(v if v is not None else ""), quote=True)


def _profile_link_html(dashboard_url: str, guest_id: Optional[str]) -> str:
    if not guest_id:
        return ""
    return (
        f' · <a href="{_e(dashboard_url)}/guests/{_e(guest_id)}" '
        f'style="color:{BRAND};font-weight:700;text-decoration:none">Profile 360 →</a>'
    )


def _lead_row_html(lead: dict, meta: str, dashboard_url: str) -> str:
    name = lead.get("name") or "Unnamed lead"
    summary = lead.get("ai_summary")
    no_contact = "" if lead.get("has_contact") else (
        f'<div style="font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{AMBER_INK};margin-top:2px">No contact details on file</div>'
    )
    summary_html = (
        f'<div style="font:12.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:3px;font-style:italic">{_e(summary)}</div>'
        if summary else ""
    )
    return f"""
      <tr><td style="padding:10px 0;border-bottom:1px solid {LINE}">
        <div style="font:700 13.5px -apple-system,Segoe UI,Roboto,sans-serif;color:{INK}">{_e(name)}</div>
        <div style="font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:1px">{_e(meta)}{_profile_link_html(dashboard_url, lead.get('guest_id'))}</div>
        {summary_html}
        {no_contact}
      </td></tr>"""


def _waiting_label(mins: Optional[int]) -> str:
    if mins is None:
        return ""
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    return f"{hours}h" if hours < 24 else f"{hours // 24}d"


def _section_rows(kind: str, rows: list[dict], dashboard_url: str) -> list[str]:
    out = []
    for r in rows[:_MAX_ROWS]:
        lead = r.get("lead") or {}
        if kind == "awaiting_reply":
            meta = f"{r.get('channel', '')} · waiting {_waiting_label(r.get('waiting_minutes'))}"
        else:  # overdue_followups
            meta = r.get("title") or "Follow-up overdue"
        out.append(_lead_row_html(lead, meta, dashboard_url))
    return out


def _section_html(kind: str, rows: list[dict], total: int, dashboard_url: str) -> str:
    if not rows:
        return ""
    title = _SECTION_TITLES.get(kind, kind.replace("_", " ").title())
    row_html = "".join(_section_rows(kind, rows, dashboard_url))
    more = ""
    if total > len(rows[:_MAX_ROWS]):
        more = (
            f'<tr><td style="padding-top:6px"><a href="{_e(dashboard_url)}/worklist" '
            f'style="display:block;text-align:center;padding:8px;font:700 11.5px -apple-system,Segoe UI,Roboto,sans-serif;'
            f'color:{BRAND};text-decoration:none;border:1.5px dashed {LINE};border-radius:8px">'
            f'+{total - len(rows[:_MAX_ROWS])} more in your worklist →</a></td></tr>'
        )
    return f"""
    <tr><td style="padding:18px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">{_e(title)} · {total}</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">{row_html}{more}</table>
    </td></tr>"""


def _phone_declines_html(items: list[dict], dashboard_url: str) -> str:
    """Phone-decline alert plan: this agent's own open "Guest declined
    phone number" Tasks (phone_decline_detector.open_tasks), rendered as
    their own section rather than folded into the generic overdue-followups
    list -- the whole point is that these read differently from an
    ordinary follow-up."""
    if not items:
        return ""
    rows = "".join(f"""
      <tr><td style="padding:10px 0;border-bottom:1px solid {LINE}">
        <div style="font:700 13.5px -apple-system,Segoe UI,Roboto,sans-serif;color:#B3261E">{_e(i['guest_name'])}</div>
        <div style="font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};margin-top:1px">
          Declined to share a phone number, waiting for a reply in the DM.{_profile_link_html(dashboard_url, i.get('guest_id'))}
        </div>
      </td></tr>""" for i in items[:_MAX_ROWS])
    return f"""
    <tr><td style="padding:18px 24px 0">
      <div style="font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.5px">Declined to share a phone number · {len(items)}</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">{rows}</table>
    </td></tr>"""


_TIME_OF_DAY_COPY = {
    "morning": "Start of day",
    "afternoon": "Midday check-in",
    "evening": "Before you sign off",
}


def render_agent_worklist_html(
    worklist: dict, *, agent_name: str, tenant_name: str, dashboard_url: str, time_of_day: str,
) -> str:
    counts = worklist["counts"]
    total_pending = sum(counts.values())
    first_name = agent_name.split()[0] if agent_name else "there"
    header_note = _TIME_OF_DAY_COPY.get(time_of_day, "Your pending leads")

    sections_html = "".join(
        _section_html(kind, worklist.get(kind) or [], counts.get(kind, 0), dashboard_url)
        for kind in _SECTION_ORDER
    )
    sections_html += _phone_declines_html(worklist.get("phone_declines") or [], dashboard_url)

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#F3F4F6">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F3F4F6;padding:24px 12px">
<tr><td align="center">
  <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;max-width:600px">

    <tr><td style="background:{BRAND};padding:20px 24px">
      <div style="font:700 18px -apple-system,Segoe UI,Roboto,sans-serif;color:#fff">Hi {_e(first_name)}, {total_pending} lead{'s' if total_pending != 1 else ''} need{'s' if total_pending == 1 else ''} your attention</div>
      <div style="font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:#CCFBF1;margin-top:2px">{_e(header_note)} · {_e(tenant_name)}</div>
    </td></tr>

    {sections_html}

    <tr><td style="padding:24px" align="center">
      <a href="{_e(dashboard_url)}/worklist" style="display:inline-block;background:{BRAND};color:#fff;text-decoration:none;font:600 14px -apple-system,Segoe UI,Roboto,sans-serif;padding:11px 22px;border-radius:8px">Open your worklist</a>
    </td></tr>

    <tr><td style="padding:0 24px 22px" align="center">
      <div style="font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{MUTED}">
        You get this at 9am, 2pm and 7pm IST while leads are still pending. Update the lead's stage or contact the guest to clear it from the next one.
      </div>
    </td></tr>

  </table>
</td></tr></table>
</body></html>"""


def render_agent_worklist_subject(worklist: dict, agent_name: str, tenant_name: str) -> str:
    counts = worklist["counts"]
    total = sum(counts.values())
    first_name = agent_name.split()[0] if agent_name else "there"
    return f"{first_name}, {total} pending lead{'s' if total != 1 else ''} at {tenant_name}"
