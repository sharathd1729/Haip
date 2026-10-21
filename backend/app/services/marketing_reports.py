"""Marketing results (agency M6): the weekly report (and its email), the monthly report against targets, and the
marketing health score. Bookings are the one source of truth; Meta's own numbers are shown next to what HAIP can
trace ("Meta says N chats, HAIP traced M"), and every report says how many bookings it cannot trace.

Monthly status per metric, by pace: projected = actual / share of the month gone (the final figure for a past month);
on_track if projected >= target, at_risk if >= 85% of it, else off_track. No target = no status, never a guess.
Targets: revenue = the workspace's sales target for the month (sales_targets, scope tenant); bookings HAIP can trace
to marketing = brand_config.marketing_studio.targets.monthly_traced_bookings (owner).
"""
import asyncio
import html
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.models.ad_metrics import AdMetric
from app.models.lead_attribution import LeadAttribution
from app.models.marketing import MarketingContent, MarketingPlan, MarketingPublishAttempt
from app.models.sales_target import SalesTarget
from app.models.tenant import Tenant
from app.models.user import User
from app.services import email_service
from app.services import marketing_attribution as attribution
from app.services import marketing_learning as learning
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

IST = ZoneInfo("Asia/Kolkata")
KEY = "reports"


def settings_of(tenant: Tenant) -> dict:
    section = ((tenant.brand_config or {}).get("marketing_studio") or {}) if tenant is not None else {}
    r = (section.get(KEY) if isinstance(section, dict) else None) or {}
    t = (section.get("targets") if isinstance(section, dict) else None) or {}
    target = t.get("monthly_traced_bookings")
    return {"weekly_email": bool(r.get("weekly_email")), "last_weekly": r.get("last_weekly"),
            "monthly_traced_bookings": target if isinstance(target, int) and target > 0 else None}


def update_settings(db: Session, tenant: Tenant, *, weekly_email: Optional[bool], monthly_traced_bookings,
                    actor_id: str) -> dict:
    if monthly_traced_bookings is not None and (not isinstance(monthly_traced_bookings, int)
                                                or not 0 <= monthly_traced_bookings <= 100_000):
        raise MarketingError(422, "bad_target", "The bookings target must be a whole number.")
    before = settings_of(tenant)
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get("marketing_studio") or {})
    reports = dict(section.get(KEY) or {})
    if weekly_email is not None:
        reports["weekly_email"] = bool(weekly_email)
    section[KEY] = reports
    if monthly_traced_bookings is not None:
        section["targets"] = {**(section.get("targets") or {}), "monthly_traced_bookings": monthly_traced_bookings or None}
    cfg["marketing_studio"] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    after = settings_of(tenant)
    append_audit(db, tenant_id=tenant.id, action="marketing.reports.settings_updated", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": after})
    return after


def _day_bounds(a: date, b: date) -> tuple[datetime, datetime]:
    return (datetime.combine(a, time.min, tzinfo=IST).astimezone(timezone.utc),
            datetime.combine(b, time.max, tzinfo=IST).astimezone(timezone.utc))


def _spend(db: Session, tenant_id: str, a: date, b: date) -> tuple[float, int]:
    s, c = (db.query(func.coalesce(func.sum(AdMetric.spend), 0), func.coalesce(func.sum(AdMetric.conversations_started), 0))
            .filter(AdMetric.tenant_id == tenant_id, AdMetric.date >= a, AdMetric.date <= b).one())
    return round(float(s or 0), 2), int(c or 0)


def _traced_chats(db: Session, tenant_id: str, a: date, b: date) -> int:
    lo, hi = _day_bounds(a, b)
    return db.query(LeadAttribution).filter(LeadAttribution.tenant_id == tenant_id, LeadAttribution.created_at >= lo,
                                            LeadAttribution.created_at <= hi).count()


def _published(db: Session, tenant_id: str, a: date, b: date) -> int:
    lo, hi = _day_bounds(a, b)
    return (db.query(MarketingPublishAttempt.content_id).filter(
        MarketingPublishAttempt.tenant_id == tenant_id, MarketingPublishAttempt.status == "published",
        MarketingPublishAttempt.published_at >= lo, MarketingPublishAttempt.published_at <= hi).distinct().count())


def period(db: Session, tenant_id: str, a: date, b: date) -> dict:
    books = attribution.bookings(db, tenant_id, a, b)
    spend, meta_chats = _spend(db, tenant_id, a, b)
    traced_revenue = round(sum(r["amount"] for r in books["bookings"] if r["chain"]["known"]), 2)
    return {"since": a.isoformat(), "until": b.isoformat(), "bookings": books["total"], "revenue": books["revenue"],
            "traced": books["traced"], "unknown": books["unknown"], "unknown_share": books["unknown_share"],
            "traced_revenue": traced_revenue, "ad_spend": spend,
            "cost_per_traced_booking": round(spend / books["traced"], 2) if spend and books["traced"] else None,
            "meta_chats": meta_chats, "haip_traced_chats": _traced_chats(db, tenant_id, a, b),
            "posts_published": _published(db, tenant_id, a, b), "by_post": books["by_post"],
            "booking_rows": books["bookings"]}


def last_full_week(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def health(db: Session, tenant: Tenant, today: date) -> dict:
    """0-100 from four equal parts, each explained: cadence, engagement trend, traceability, approval backlog."""
    a, b = today - timedelta(days=27), today
    parts = []
    plan = (db.query(MarketingPlan).filter(MarketingPlan.tenant_id == tenant.id, MarketingPlan.status == "ready")
            .order_by(MarketingPlan.created_at.desc()).first())
    planned = len([e for e in ((plan.body or {}).get("calendar") or []) if a.isoformat() <= e.get("date", "") <= b.isoformat()
                   and e.get("kind") != "story"]) if plan else 0
    expected = planned or 8
    posted = _published(db, tenant.id, a, b)
    parts.append({"key": "cadence", "score": round(25 * min(1.0, posted / expected), 1),
                  "detail": f"{posted} posts in 28 days against {expected} {'planned' if planned else 'expected (2 a week)'}"})
    posts = learning.published_posts(db, tenant.id)
    lo, mid = _day_bounds(a, b)[0], _day_bounds(a - timedelta(days=28), a - timedelta(days=1))[0]

    def rates(x, y):
        return [p["rate"] for p in posts if p["rate"] is not None and p["published_at"] is not None
                and x <= (p["published_at"] if p["published_at"].tzinfo else p["published_at"].replace(tzinfo=timezone.utc)) < y]
    now_r, before_r = rates(lo, _day_bounds(b, b)[1]), rates(mid, lo)
    if now_r and before_r and median(before_r) > 0:
        ratio = median(now_r) / median(before_r)
        parts.append({"key": "engagement", "score": round(25 * min(1.0, ratio), 1),
                      "detail": f"engagement {int(round(ratio * 100))}% of the 28 days before"})
    else:
        parts.append({"key": "engagement", "score": 12.5, "detail": "not enough measured posts to compare yet"})
    books = attribution.bookings(db, tenant.id, a, b)
    if books["total"]:
        share = books["traced"] / books["total"]
        parts.append({"key": "traceability", "score": round(25 * share, 1),
                      "detail": f"{books['traced']} of {books['total']} bookings traced to a post or ad"})
    else:
        parts.append({"key": "traceability", "score": 12.5, "detail": "no bookings in the last 28 days"})
    stale = (db.query(MarketingContent).filter(MarketingContent.tenant_id == tenant.id, MarketingContent.status == "in_review",
                                               MarketingContent.updated_at < datetime.now(timezone.utc) - timedelta(hours=48))
             .count())
    parts.append({"key": "approvals", "score": float(max(0, 25 - 5 * stale)),
                  "detail": f"{stale} posts waiting over 2 days for approval" if stale else "nothing waiting over 2 days"})
    return {"score": int(round(sum(p["score"] for p in parts))), "parts": parts, "as_of": today.isoformat()}


def weekly(db: Session, tenant: Tenant, today: Optional[date] = None) -> dict:
    today = today or datetime.now(IST).date()
    a, b = last_full_week(today)
    return {"week": period(db, tenant.id, a, b), "health": health(db, tenant, today)}


def _status(actual: float, target: Optional[float], elapsed: float) -> Optional[str]:
    if not target:
        return None
    projected = actual / max(elapsed, 0.05) if elapsed < 1 else actual
    ratio = projected / target
    return "on_track" if ratio >= 1 else "at_risk" if ratio >= 0.85 else "off_track"


def monthly(db: Session, tenant: Tenant, month: date, *, today: Optional[date] = None) -> dict:
    today = today or datetime.now(IST).date()
    start = month.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    prev_start = (start - timedelta(days=1)).replace(day=1)
    upto = min(end, today)
    elapsed = 1.0 if today > end else max(0.0, ((upto - start).days + 1) / ((end - start).days + 1))
    this, last = period(db, tenant.id, start, upto), period(db, tenant.id, prev_start, start - timedelta(days=1))
    rev_target = (db.query(SalesTarget.target_amount).filter(SalesTarget.tenant_id == tenant.id, SalesTarget.scope_type == "tenant",
                                                             SalesTarget.period_month == start).scalar())
    traced_target = settings_of(tenant)["monthly_traced_bookings"]
    metrics = [
        {"key": "revenue", "label": "Revenue booked", "this": this["revenue"], "last": last["revenue"],
         "target": float(rev_target) if rev_target else None},
        {"key": "bookings", "label": "Bookings", "this": this["bookings"], "last": last["bookings"], "target": None},
        {"key": "traced", "label": "Bookings traced to marketing", "this": this["traced"], "last": last["traced"],
         "target": traced_target},
        {"key": "ad_spend", "label": "Ad spend", "this": this["ad_spend"], "last": last["ad_spend"], "target": None},
        {"key": "cost_per_traced_booking", "label": "Cost per traced booking", "this": this["cost_per_traced_booking"],
         "last": last["cost_per_traced_booking"], "target": None},
    ]
    for m in metrics:
        m["status"] = _status(m["this"] or 0, m["target"], elapsed)
    return {"month": start.isoformat()[:7], "elapsed": round(elapsed, 2), "metrics": metrics,
            "this": {k: v for k, v in this.items() if k != "booking_rows"},
            "last": {k: v for k, v in last.items() if k != "booking_rows"},
            "meta_vs_haip": {"meta_chats": this["meta_chats"], "haip_traced_chats": this["haip_traced_chats"]}}


# ── Weekly email ────────────────────────────────────────────────────────────────────────────────────────────────────

def _inr(v) -> str:
    n = int(round(float(v or 0)))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + parts) + "," + tail
    return f"Rs {s}"


def render_weekly(tenant: Tenant, report: dict) -> tuple[str, str, str]:
    w, h = report["week"], report["health"]
    subject = f"Marketing this week: {w['bookings']} bookings, {w['traced']} traced to a post or ad"
    lines = [f"{tenant.name}: marketing, {w['since']} to {w['until']}", "",
             f"Bookings: {w['bookings']} ({_inr(w['revenue'])}). Traced to a post or ad: {w['traced']}; "
             f"unknown: {w['unknown']}.",
             f"Ad spend: {_inr(w['ad_spend'])}" + (f", {_inr(w['cost_per_traced_booking'])} per traced booking."
                                                    if w["cost_per_traced_booking"] else "."),
             f"Meta says {w['meta_chats']} chats started; HAIP traced {w['haip_traced_chats']}.",
             f"Posts published: {w['posts_published']}. Health score: {h['score']}/100.", "", "Behind each booking:"]
    for r in w["booking_rows"]:
        who = r["credited_title"] or "unknown"
        said = f" (guest said: {r['heard_about']})" if r["heard_about"] else ""
        lines.append(f"- {r['check_in']} {r['property'] or ''} {_inr(r['amount'])}: {who}{said}")
    if not w["booking_rows"]:
        lines.append("- no bookings this week")
    lines += ["", "Health: " + "; ".join(p["detail"] for p in h["parts"])]
    text = "\n".join(lines)
    items = "".join(f"<li>{html.escape(x[2:])}</li>" for x in lines if x.startswith("- "))
    paras = "".join(f"<p>{html.escape(x)}</p>" for x in lines if x and not x.startswith("- "))
    body = paras + (f"<ul>{items}</ul>" if items else "")
    return subject, f"<div style=\"font-family:sans-serif;font-size:14px;line-height:1.5\">{body}</div>", text


def send_weekly(db: Session, tenant: Tenant, *, today: Optional[date] = None,
                sender: Optional[Callable[..., bool]] = None) -> dict:
    """Email the weekly report to the workspace's owners and managers, once per week, if the owner switched it on."""
    s = settings_of(tenant)
    today = today or datetime.now(IST).date()
    week_start = last_full_week(today)[0].isoformat()
    if not s["weekly_email"]:
        return {"sent": 0, "reason": "off"}
    if s["last_weekly"] == week_start:
        return {"sent": 0, "reason": "already sent"}
    report = weekly(db, tenant, today)
    subject, body_html, text = render_weekly(tenant, report)
    users = (db.query(User).filter(User.tenant_id == tenant.id, User.is_active.is_(True), User.email.isnot(None)).all())
    send = sender or (lambda **kw: asyncio.run(email_service._send(**kw)))
    sent = 0
    for u in users:
        role = getattr(u.role, "value", u.role)
        if role not in ("owner", "manager") or "@" not in (u.email or ""):
            continue
        try:
            sent += 1 if send(to=u.email, subject=subject, html=body_html, text=text) else 0
        except Exception as exc:  # noqa: BLE001  one address failing must not stop the others
            log.warning("marketing_weekly_email_failed", tenant_id=tenant.id, user_id=u.id, error=str(exc)[:200])
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get("marketing_studio") or {})
    section[KEY] = {**(section.get(KEY) or {}), "last_weekly": week_start}
    cfg["marketing_studio"] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.weekly_report.sent", actor_user_id=None,
                 target_type="tenant", target_id=tenant.id, payload={"actor": "system", "week": week_start, "sent": sent})
    db.commit()
    return {"sent": sent, "week": week_start}
