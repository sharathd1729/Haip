"""Before / after impact view: composes the measured numbers (impact_metrics + the shared lead/booking/cash metrics) with the
owner-entered baselines, for one go-live date.

Two windows of ``days`` IST days each:
  * BEFORE = the ``days`` days just before go-live (HAIP measures what it holds: personal WhatsApp history reaches back
    30 days, calls start at the IVR move, so this is often thin; the owner-entered baseline is the main "before" figure);
  * WITH HAIP = the latest ``days`` days up to today, never starting before go-live.

Rules kept here: every figure carries its period; a money figure needs revenue.read, else the block is ``{"restricted": true}``
(never 0); a change is shown only against a real, non-zero baseline (``None`` otherwise: never "-100%" against nothing).
Baselines are edited only by the owner, through ``save_baseline`` / ``delete_baseline``, each audited with before/after values.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.impact import ImpactBaseline, ImpactProfile
from app.services import impact_metrics as im
from app.services import kpi_metrics, lead_metrics
from app.services.date_presets import ist_range_to_utc, today_ist

DEFAULT_DAYS = 30
MIN_DAYS, MAX_DAYS = 7, 180

# key: label, unit, lower_is_better, money, definition. The "with HAIP" value of each is picked in _value().
BASELINE_METRICS: dict[str, dict] = {
    "first_reply_median_minutes": {"label": "Median first reply", "unit": "minutes", "lower_is_better": True, "money": False,
        "definition": "Half of guest messages (WhatsApp and Instagram, one per guest turn) got their first reply faster than this. "
                      "AI and staff replies both count; internal notes and failed sends do not."},
    "first_reply_p90_minutes": {"label": "Slowest 10% of first replies", "unit": "minutes", "lower_is_better": True, "money": False,
        "definition": "90% of answered guest turns got their first reply within this time (p90)."},
    "answered_within_5_pct": {"label": "Answered within 5 min", "unit": "%", "lower_is_better": False, "money": False,
        "definition": "Share of guest turns whose first reply came within 5 minutes. Unanswered turns count as not answered."},
    "answered_within_15_pct": {"label": "Answered within 15 min", "unit": "%", "lower_is_better": False, "money": False,
        "definition": "Share of guest turns whose first reply came within 15 minutes. Unanswered turns count as not answered."},
    "answered_within_60_pct": {"label": "Answered within 1 hour", "unit": "%", "lower_is_better": False, "money": False,
        "definition": "Share of guest turns whose first reply came within 60 minutes. Unanswered turns count as not answered."},
    "after_hours_within_15_pct": {"label": "After-hours answered within 15 min", "unit": "%", "lower_is_better": False, "money": False,
        "definition": "Guest turns that started outside business hours (workspace hours, else Mon-Fri 9-21, Sat 10-18, Sun 10-14 "
                      "IST), answered within 15 minutes by anyone."},
    "new_leads_per_30d": {"label": "New leads per 30 days", "unit": "count", "lower_is_better": False, "money": False,
        "definition": "People whose usable phone number was first captured, scaled to 30 days. A DM without a number is not a lead."},
    "lead_to_quote_pct": {"label": "Leads quoted", "unit": "%", "lower_is_better": False, "money": False,
        "definition": "Of the people who became leads in the period, the share sent a quote so far (cohort)."},
    "lead_to_booking_pct": {"label": "Leads that booked", "unit": "%", "lower_is_better": False, "money": False,
        "definition": "Of the people who became leads in the period, the share with a live booking so far (cohort; recent periods "
                      "are still maturing)."},
    "missed_calls_returned_pct": {"label": "Missed calls called back", "unit": "%", "lower_is_better": False, "money": False,
        "definition": "Inbound calls nobody answered that were later returned by a call to the same guest."},
    "callback_median_minutes": {"label": "Median time to call back", "unit": "minutes", "lower_is_better": True, "money": False,
        "definition": "For missed calls that were returned: half were called back faster than this."},
    "revenue_booked_per_30d": {"label": "Bookings value per 30 days", "unit": "inr", "lower_is_better": False, "money": True,
        "definition": "Stay charge of bookings made (confirmed, checked in or out; cancelled excluded), scaled to 30 days. Add-ons "
                      "and taxes are not included."},
    "revenue_collected_per_30d": {"label": "Cash collected per 30 days", "unit": "inr", "lower_is_better": False, "money": True,
        "definition": "Payments received by payment date, scaled to 30 days. Refunds are shown separately, not subtracted."},
}


class ImpactError(ValueError):
    """A request the impact view refuses (shown to the user as is)."""


# ── windows ──────────────────────────────────────────────────────────────────────────────────────────────────

def windows(go_live: date, days: int, today: Optional[date] = None) -> dict:
    today = today or today_ist()
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise ImpactError(f"days must be between {MIN_DAYS} and {MAX_DAYS}")
    if go_live > today:
        raise ImpactError("The go-live date is in the future")
    after_from = max(go_live, today - timedelta(days=days - 1))
    before = (go_live - timedelta(days=days), go_live - timedelta(days=1))
    return {"before": {"from": before[0].isoformat(), "to": before[1].isoformat(), "days": days},
            "with": {"from": after_from.isoformat(), "to": today.isoformat(), "days": (today - after_from).days + 1}}


def _minutes(seconds: Optional[float]) -> Optional[float]:
    return round(seconds / 60, 1) if seconds is not None else None


def _measure(db: Session, tenant, w: dict, can_revenue: bool, now: Optional[datetime]) -> dict:
    s, e, _, _ = ist_range_to_utc(w["from"], w["to"])
    replies = im.first_replies(db, tenant, s, e, now=now)
    out = {"period": w, "replies": replies, "funnel": im.funnel(db, tenant.id, s, e),
           "new_leads": lead_metrics.count_new_leads(db, tenant.id, s, e),
           "missed_calls": im.missed_calls(db, tenant.id, s, e), "lost": im.lost_enquiries(db, tenant.id, s, e)}
    if can_revenue:
        _, booked = kpi_metrics.booked_totals(db, tenant.id, s, e)
        cash = kpi_metrics.payment_totals(db, tenant.id, date.fromisoformat(w["from"]), date.fromisoformat(w["to"]))
        out["money"] = {"booked_value": round(booked, 2), "collected": round(cash["collected"], 2), "refunded": round(cash["refunded"], 2)}
    return out


def _value(key: str, m: dict) -> tuple[Optional[float], Optional[int]]:
    """(the measured value of a baseline metric in one window, the number of items it rests on)."""
    r, f, calls, scale = m["replies"], m["funnel"], m["missed_calls"], 30 / m["period"]["days"]
    pick = {
        "first_reply_median_minutes": (_minutes(r["all"]["median_seconds"]), r["all"]["answered"]),
        "first_reply_p90_minutes": (_minutes(r["all"]["p90_seconds"]), r["all"]["answered"]),
        "answered_within_5_pct": (r["all"]["within_pct"]["5"], r["all"]["turns"]),
        "answered_within_15_pct": (r["all"]["within_pct"]["15"], r["all"]["turns"]),
        "answered_within_60_pct": (r["all"]["within_pct"]["60"], r["all"]["turns"]),
        "after_hours_within_15_pct": (r["after_hours"]["within_15_pct"], r["after_hours"]["turns"]),
        "new_leads_per_30d": (round(m["new_leads"] * scale, 1), m["new_leads"]),
        "lead_to_quote_pct": (f["lead_to_quote_pct"], f["leads"]),
        "lead_to_booking_pct": (f["lead_to_booking_pct"], f["leads"]),
        "missed_calls_returned_pct": (calls["returned_pct"], calls["missed"]),
        "callback_median_minutes": (_minutes(calls["median_callback_seconds"]), calls["returned"]),
    }
    if key in pick:
        return pick[key]
    money = m.get("money")
    if money is None:
        return None, None
    field = "booked_value" if key == "revenue_booked_per_30d" else "collected"
    return round(money[field] * scale, 2), None


def change(before: Optional[float], after: Optional[float], unit: str, lower_is_better: bool) -> Optional[dict]:
    """The difference to show, or None when there is no real baseline (none, or 0) or nothing measured since."""
    if before is None or after is None or before == 0:
        return None
    if unit == "%":
        diff = round(after - before, 1)
        kind = "points"
    else:
        diff = round((after - before) / before * 100, 1)
        kind = "pct"
    better = None if diff == 0 else ((diff < 0) == lower_is_better)
    return {"kind": kind, "value": diff, "better": better}


def _baseline_out(b: ImpactBaseline) -> dict:
    return {"metric": b.metric, "value": float(b.value), "period_label": b.period_label, "source_note": b.source_note,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None, "source": "owner_entered"}


def tiles(baselines: dict[str, ImpactBaseline], before: dict, after: dict, can_revenue: bool) -> list[dict]:
    out = []
    for key, spec in BASELINE_METRICS.items():
        base = {"key": key, "label": spec["label"], "unit": spec["unit"], "definition": spec["definition"],
                "lower_is_better": spec["lower_is_better"]}
        if spec["money"] and not can_revenue:
            out.append({**base, "restricted": True})
            continue
        owner = baselines.get(key)
        measured_v, measured_n = _value(key, before)
        with_v, with_n = _value(key, after)
        reference = float(owner.value) if owner is not None else measured_v
        out.append({**base, "restricted": False,
                    "before": {"owner": _baseline_out(owner) if owner else None,
                               "measured": {"value": measured_v, "n": measured_n, "period": before["period"]}},
                    "with": {"value": with_v, "n": with_n, "period": after["period"]},
                    "change": change(reference, with_v, spec["unit"], spec["lower_is_better"]),
                    "change_against": "owner_entered" if owner is not None else ("measured" if measured_v is not None else None)})
    return out


# ── the view ─────────────────────────────────────────────────────────────────────────────────────────────────

def get_profile(db: Session, tenant_id: str) -> Optional[ImpactProfile]:
    return db.query(ImpactProfile).filter_by(tenant_id=tenant_id).first()


def baselines_for(db: Session, tenant_id: str) -> dict[str, ImpactBaseline]:
    return {b.metric: b for b in db.query(ImpactBaseline).filter_by(tenant_id=tenant_id).all()}


def build(db: Session, tenant, *, go_live: Optional[date], days: Optional[int], can_revenue: bool,
          today: Optional[date] = None, now: Optional[datetime] = None) -> dict:
    profile = get_profile(db, tenant.id)
    go_live = go_live or (profile.go_live_date if profile else None)
    days = days or (profile.window_days if profile else DEFAULT_DAYS)
    if go_live is None:
        return {"go_live": None, "days": days, "needs_go_live": True}
    w = windows(go_live, days, today)
    before = _measure(db, tenant, w["before"], can_revenue, now)
    after = _measure(db, tenant, w["with"], can_revenue, now)
    baselines = baselines_for(db, tenant.id)
    month_from = date.fromisoformat(w["before"]["from"])
    revenue = ({"restricted": False, "months": im.revenue_by_month(db, tenant.id, month_from, date.fromisoformat(w["with"]["to"])),
                "go_live_month": go_live.strftime("%Y-%m")} if can_revenue else {"restricted": True})
    return {
        "go_live": go_live.isoformat(), "days": days, "needs_go_live": False, "windows": w,
        "generated_at": datetime.now(timezone.utc).isoformat(), "timezone": "Asia/Kolkata",
        "tiles": tiles(baselines, before, after, can_revenue),
        "before": before, "with": after, "revenue": revenue,
        "notes": ["Before HAIP: owner-entered figures where given, otherwise what HAIP itself recorded in the window before "
                  "go-live (often little: personal WhatsApp history reaches back 30 days, calls start at the IVR move).",
                  "Leads and bookings are a cohort: people who became leads in the window and what they did so far."],
    }


# ── baselines (owner only) ───────────────────────────────────────────────────────────────────────────────────

def save_baseline(db: Session, tenant_id: str, user_id: str, metric: str, value: float, period_label: str,
                  source_note: Optional[str]) -> ImpactBaseline:
    if metric not in BASELINE_METRICS:
        raise ImpactError(f"Unknown metric: {metric}")
    row = db.query(ImpactBaseline).filter_by(tenant_id=tenant_id, metric=metric).first()
    before = _baseline_out(row) if row else None
    if row is None:
        row = ImpactBaseline(tenant_id=tenant_id, metric=metric, created_by=user_id, value=Decimal("0"), period_label="")
        db.add(row)
    row.value = Decimal(str(value))
    row.period_label = period_label
    row.source_note = source_note
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="impact.baseline_saved", actor_user_id=user_id, target_type="impact_baseline",
                 target_id=row.id, payload={"metric": metric, "before": before, "after": _baseline_out(row)})
    db.commit()
    db.refresh(row)
    return row


def delete_baseline(db: Session, tenant_id: str, user_id: str, metric: str) -> bool:
    row = db.query(ImpactBaseline).filter_by(tenant_id=tenant_id, metric=metric).first()
    if row is None:
        return False
    before = _baseline_out(row)
    db.delete(row)
    append_audit(db, tenant_id=tenant_id, action="impact.baseline_deleted", actor_user_id=user_id, target_type="impact_baseline",
                 target_id=row.id, payload={"metric": metric, "before": before})
    db.commit()
    return True


def save_settings(db: Session, tenant_id: str, user_id: str, go_live: date, days: int) -> ImpactProfile:
    if go_live > today_ist():
        raise ImpactError("The go-live date is in the future")
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise ImpactError(f"days must be between {MIN_DAYS} and {MAX_DAYS}")
    profile = get_profile(db, tenant_id)
    before = {"go_live": profile.go_live_date.isoformat() if profile and profile.go_live_date else None,
              "days": profile.window_days if profile else None}
    if profile is None:
        profile = ImpactProfile(tenant_id=tenant_id, case_study_status="draft")
        db.add(profile)
    profile.go_live_date, profile.window_days = go_live, days
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="impact.settings_saved", actor_user_id=user_id, target_type="impact_profile",
                 target_id=profile.id, payload={"before": before, "after": {"go_live": go_live.isoformat(), "days": days}})
    db.commit()
    return profile
