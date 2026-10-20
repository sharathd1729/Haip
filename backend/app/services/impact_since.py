"""The "Since HAIP" card on the Owner Command Center: five headline figures, before go-live vs since, side by side.

A thin composition of shared definitions (docs/analytics/KPI_METRIC_CATALOGUE.md section 14, "Since HAIP card"); nothing here
defines a metric of its own:
  * leads           = leads.identified_new (lead_metrics.count_new_leads)
  * bookings, value = stays.booked (kpi_metrics.booking_filters / booked_totals), split by the booking's channel_source so the
                      "before" figure says where it came from (shared calendar, entered in HAIP, PMS import...)
  * first reply     = message_metrics.chat_response_by_agent_source (human replies, by source), with mirrored phone history
                      INCLUDED in both windows: before go-live it is the only record of reply times there is
  * AI drafts sent  = ai_draft_outcomes sent_verbatim + sent_edited (the agent scorecard's "approved" rule)

Windows: the go-live date and window come from the impact profile (owner sets them on /dashboard/impact). WITH HAIP = the
latest N days up to today (impact_service.windows); BEFORE = the same number of days just before go-live, so both windows are
always the same length. Every "before" figure carries a ``source`` line and ``has_data``; a change is shown only against a real,
non-zero baseline (impact_service.change), never "-100%" against nothing. Without bookings.read / revenue.read the tile is
``{"restricted": true}`` (never 0).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.property import Stay
from app.services import impact_service, kpi_metrics, lead_metrics
from app.services.date_presets import ist_range_to_utc
from app.services.message_metrics import chat_response_by_agent_source

APPROVED_OUTCOMES = ("sent_verbatim", "sent_edited")

BOOKING_SOURCE_LABELS = {
    "google_calendar": "from the shared calendar", "direct": "entered in HAIP", "reseller": "through resellers",
    "hostaway": "imported from the PMS", "rentalwise": "imported from the PMS", "retalwise": "imported from the PMS",
    "airbnb": "from Airbnb", "booking": "from Booking.com", "vrbo": "from Vrbo", None: "with no source recorded",
}
REPLY_SOURCE_LABELS = {"personal_whatsapp": "personal WhatsApp", "whatsapp_cloud": "WhatsApp Business number",
                       "instagram": "Instagram"}


def equal_windows(go_live: date, days: int, today: Optional[date] = None) -> dict:
    """WITH HAIP as on the impact page; BEFORE trimmed to the same length (a recent go-live gives a short WITH window)."""
    w = impact_service.windows(go_live, days, today)
    n = w["with"]["days"]
    before_from, before_to = go_live - timedelta(days=n), go_live - timedelta(days=1)
    return {"before": {"from": before_from.isoformat(), "to": before_to.isoformat(), "days": n}, "with": w["with"]}


def _measure(db: Session, tenant_id: str, w: dict, can_bookings: bool, can_revenue: bool) -> dict:
    s, e, s_dt, e_dt = ist_range_to_utc(w["from"], w["to"])
    out: dict = {"leads": lead_metrics.count_new_leads(db, tenant_id, s, e)}
    if can_bookings or can_revenue:
        rows = (db.query(Stay.channel_source, func.count(Stay.id), func.coalesce(func.sum(Stay.total_amount), 0))
                .filter(*kpi_metrics.booking_filters(tenant_id, s, e)).group_by(Stay.channel_source).all())
        out["bookings"] = sum(int(n) for _, n, _ in rows)
        out["booked_value"] = round(sum(float(v or 0) for _, _, v in rows), 2)
        out["booking_sources"] = sorted(((src, int(n)) for src, n, _ in rows), key=lambda r: -r[1])
    out["replies"] = chat_response_by_agent_source(db, tenant_id, since=s_dt, until=e_dt, include_history=True)
    out["ai_drafts_sent"] = int(db.query(func.count(AIDraftOutcome.id)).filter(
        AIDraftOutcome.tenant_id == tenant_id, AIDraftOutcome.outcome.in_(APPROVED_OUTCOMES),
        AIDraftOutcome.created_at >= s_dt, AIDraftOutcome.created_at <= e_dt).scalar() or 0)
    return out


def _booking_source_line(sources: list[tuple[Optional[str], int]]) -> str:
    if not sources:
        return "No bookings recorded in HAIP for these days."
    parts = [f"{n} {BOOKING_SOURCE_LABELS.get(src, f'from {src}')}" for src, n in sources]
    return "HAIP's booking records: " + ", ".join(parts) + "."


def _reply_source_line(replies: dict) -> str:
    parts = [f"{REPLY_SOURCE_LABELS[s]} ({v['response_count']} {'reply' if v['response_count'] == 1 else 'replies'})"
             for s, v in replies["by_source"].items() if v]
    if not parts:
        return "No replies recorded before go-live."
    return "Replies HAIP holds from " + ", ".join(parts) + "; personal WhatsApp before go-live is the mirrored phone history (text only)."


def _minutes(replies: dict) -> Optional[float]:
    a = replies["all"]
    return round(a["avg_seconds"] / 60, 1) if a and a["avg_seconds"] is not None else None


def _tile(key: str, label: str, unit: str, before_v, before_n: Optional[int], with_v, source: str, *,
          lower_is_better: bool = False, definition: str) -> dict:
    has_data = before_v not in (None, 0)
    return {"key": key, "label": label, "unit": unit, "lower_is_better": lower_is_better, "definition": definition,
            "restricted": False,
            "before": {"value": before_v, "n": before_n, "has_data": has_data, "source": source},
            "with": {"value": with_v},
            "change": impact_service.change(before_v, with_v, unit, lower_is_better) if has_data else None}


def tiles(before: dict, after: dict, can_bookings: bool, can_revenue: bool) -> list[dict]:
    out = [_tile("leads", "New leads", "count", before["leads"], before["leads"], after["leads"],
                 "People whose phone number HAIP recorded before go-live. Leads were not captured before HAIP, so this is "
                 "usually empty.",
                 definition="People whose usable phone number was first captured in the window (a DM alone is not a lead).")]
    if can_bookings:
        out.append(_tile("bookings", "Bookings made", "count", before["bookings"], before["bookings"], after["bookings"],
                         _booking_source_line(before["booking_sources"]),
                         definition="Bookings created in the window (confirmed, checked in or out; cancelled excluded)."))
    else:
        out.append({"key": "bookings", "label": "Bookings made", "restricted": True})
    if can_revenue:
        out.append(_tile("booked_value", "Bookings value", "inr", before["booked_value"], before["bookings"], after["booked_value"],
                         _booking_source_line(before["booking_sources"]),
                         definition="Stay charge of the bookings made in the window. Add-ons and taxes are not included."))
    else:
        out.append({"key": "booked_value", "label": "Bookings value", "restricted": True})
    b_all, a_all = before["replies"]["all"], after["replies"]["all"]
    out.append(_tile("first_reply_minutes", "Average first reply by the team", "minutes", _minutes(before["replies"]),
                     b_all["response_count"] if b_all else 0, _minutes(after["replies"]), _reply_source_line(before["replies"]),
                     lower_is_better=True,
                     definition="Average time from a guest's message to the first reply a person sent (WhatsApp and "
                                "Instagram, group chats left out). AI replies sent on their own are not in this figure."))
    out.append(_tile("ai_drafts_sent", "AI drafts approved and sent", "count", before["ai_drafts_sent"], before["ai_drafts_sent"],
                     after["ai_drafts_sent"], "HAIP's AI drafts did not exist before go-live.",
                     definition="AI-drafted replies a person sent as written or after editing."))
    return out


def by_source(replies: dict) -> dict:
    return {s: ({"avg_minutes": round(v["avg_seconds"] / 60, 1) if v["avg_seconds"] is not None else None,
                 "replies": v["response_count"]} if v else None)
            for s, v in replies["by_source"].items()}


def build(db: Session, tenant_id: str, *, can_bookings: bool, can_revenue: bool, today: Optional[date] = None) -> dict:
    profile = impact_service.get_profile(db, tenant_id)
    days = profile.window_days if profile and profile.window_days else impact_service.DEFAULT_DAYS
    if profile is None or profile.go_live_date is None:
        return {"needs_go_live": True, "go_live": None, "days": days}
    w = equal_windows(profile.go_live_date, days, today)
    before = _measure(db, tenant_id, w["before"], can_bookings, can_revenue)
    after = _measure(db, tenant_id, w["with"], can_bookings, can_revenue)
    return {
        "needs_go_live": False, "go_live": profile.go_live_date.isoformat(), "days": days, "windows": w,
        "timezone": "Asia/Kolkata",
        "tiles": tiles(before, after, can_bookings, can_revenue),
        "replies_by_source": {"before": by_source(before["replies"]), "with": by_source(after["replies"])},
    }
