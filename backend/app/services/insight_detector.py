"""
AI Insights Engine — Phase 1 detectors.

Each detector follows the pattern:
    def detect_XX(db, tenant_id) -> list[dict] | None
    Returns a list of insight dicts to upsert, or None/[] if condition not met.

run_all_detectors(db, tenant_id) calls every detector, upserts results,
and auto-resolves insights whose conditions no longer hold.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case

from app.models.insight import Insight, InsightSeverity, InsightCategory
from app.models.inquiry import Inquiry, InquiryStage
from app.models.call import Call, CallDirection
from app.services import call_status_service
from app.models.conversation import Message, Conversation, MessageDirection
from app.models.property import Stay, Property
from app.models.integration import Integration

log = logging.getLogger(__name__)

_NOW = lambda: datetime.now(timezone.utc)

# ─── Upsert helper ─────────────────────────────────────────────────────────────

def _upsert_insight(db: Session, tenant_id: str, payload: dict) -> None:
    """
    Insert or update an insight row.
    Keyed by (tenant_id, category_code, target_id).
    If an active (non-dismissed) row already exists, update title/body/data_snapshot.
    """
    code      = payload["category_code"]
    target_id = payload.get("target_id")

    existing = db.query(Insight).filter(
        Insight.tenant_id == tenant_id,
        Insight.category_code == code,
        Insight.target_id == target_id,
        Insight.is_dismissed == False,
        Insight.is_auto_resolved == False,
    ).first()

    if existing:
        existing.title         = payload["title"]
        existing.body          = payload.get("body")
        existing.data_snapshot = payload.get("data_snapshot")
        existing.expires_at    = payload.get("expires_at")
        existing.updated_at    = _NOW()
    else:
        row = Insight(
            tenant_id     = tenant_id,
            category_code = code,
            target_id     = target_id,
            category      = payload["category"],
            severity      = payload.get("severity", InsightSeverity.MEDIUM),
            title         = payload["title"],
            body          = payload.get("body"),
            cta_label     = payload.get("cta_label"),
            cta_href      = payload.get("cta_href"),
            data_snapshot = payload.get("data_snapshot"),
            expires_at    = payload.get("expires_at"),
        )
        db.add(row)


def _auto_resolve(db: Session, tenant_id: str, category_code: str, target_id: Optional[str] = None) -> None:
    """Mark an insight as auto-resolved because its condition no longer holds."""
    q = db.query(Insight).filter(
        Insight.tenant_id == tenant_id,
        Insight.category_code == category_code,
        Insight.is_dismissed == False,
        Insight.is_auto_resolved == False,
    )
    if target_id is not None:
        q = q.filter(Insight.target_id == target_id)
    for row in q.all():
        row.is_auto_resolved  = True
        row.auto_resolved_at  = _NOW()


# ─── CATEGORY A — Urgency Alerts ──────────────────────────────────────────────

def _uncontacted_leads(db: Session, tenant_id: str) -> list[dict]:
    """New leads nobody has contacted yet, read off the ONE work queue (work_queue_service, kind ``new_lead``): people with a
    usable phone number (guests.lead_identified_at) that no person has called or written to since the number arrived, the
    cold tail (severity ``stale``) left out as on Home and in the nav badge.

    A1/A2 used to count every enquiry still in the legacy ``NEW`` stage with no ``first_response_at``. That swept in every old
    Instagram / WhatsApp DM and auto-created conversation enquiry with no phone (a DM is not a lead, CLAUDE.md "Lead
    definition"), so Home's "What the AI noticed" said "2169 leads not followed up in 24h" while My day had a handful."""
    from app.models.tenant import Tenant
    from app.services import work_queue_service

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        return []
    res = work_queue_service.build(db, tenant, None, kinds=["new_lead"])
    return [i for i in res["items"] if i.get("kind") == "new_lead" and i.get("severity") != "stale"]


def _since(item: dict) -> Optional[datetime]:
    raw = item.get("since")
    if not raw:
        return None
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def detect_A1(db: Session, tenant_id: str) -> None:
    """A1: new leads (a phone number on file) that no person has contacted for 24 h or more -- work queue kind new_lead."""
    cutoff = _NOW() - timedelta(hours=24)
    late = [i for i in _uncontacted_leads(db, tenant_id) if (_since(i) or _NOW()) <= cutoff]
    count = len({i.get("guest_id") or i.get("title") for i in late})

    if count >= 1:
        # Estimate revenue at risk from the budgets on these people's open enquiries
        inquiry_ids = [i["inquiry_id"] for i in late if i.get("inquiry_id")]
        rev = (db.query(func.sum(Inquiry.budget)).filter(
            Inquiry.tenant_id == tenant_id, Inquiry.id.in_(inquiry_ids), Inquiry.budget.isnot(None),
        ).scalar() or 0) if inquiry_ids else 0
        rev_str = f" — ₹{rev/100000:.1f}L at risk" if rev > 0 else ""
        _upsert_insight(db, tenant_id, {
            "category_code": "A1",
            "category":      InsightCategory.URGENCY,
            "severity":      InsightSeverity.CRITICAL,
            "title":         f"{count} new lead{'s' if count > 1 else ''} not contacted in 24h{rev_str}",
            "body":          f"{count} {'people' if count > 1 else 'person'} shared a phone number and nobody has called or written "
                             f"to them for over 24 hours.",
            "cta_label":     "Open My day",
            "cta_href":      "/dashboard/my-day?kind=new_lead",
            "data_snapshot": {"count": count, "revenue_at_risk": float(rev)},
            "expires_at":    _NOW() + timedelta(hours=4),
        })
    else:
        _auto_resolve(db, tenant_id, "A1")


def detect_A2(db: Session, tenant_id: str) -> None:
    """A2: new leads past the first-contact target but not yet urgent -- work queue new_lead items at severity ``late``
    (work_queue_service.SLA_MINUTES["new_lead"]), so this and My day agree on who is close to breaching."""
    from app.services.work_queue_service import SLA_MINUTES

    late_at, urgent_at = SLA_MINUTES["new_lead"][0], SLA_MINUTES["new_lead"][1]
    near = [i for i in _uncontacted_leads(db, tenant_id) if i.get("severity") == "late"]
    count = len({i.get("guest_id") or i.get("title") for i in near})

    if count >= 1:
        _upsert_insight(db, tenant_id, {
            "category_code": "A2",
            "category":      InsightCategory.URGENCY,
            "severity":      InsightSeverity.HIGH,
            "title":         f"{count} new lead{'s are' if count > 1 else ' is'} past the {late_at}-minute first-call target",
            "body":          f"Call them before they have waited {urgent_at} minutes.",
            "cta_label":     "Call now",
            "cta_href":      "/dashboard/my-day?kind=new_lead",
            "data_snapshot": {"count": count, "sla_minutes": late_at},
            "expires_at":    _NOW() + timedelta(minutes=15),
        })
    else:
        _auto_resolve(db, tenant_id, "A2")


def detect_A3(db: Session, tenant_id: str) -> None:
    """A3: Booking cancellation risk — confirmed stays with no comm in 7d, check-in ≤14d."""
    today = _NOW().date().isoformat()
    in_14d = (_NOW() + timedelta(days=14)).date().isoformat()
    inactive_since = (_NOW() - timedelta(days=7)).isoformat()

    # Conversations linked to upcoming confirmed stays with no recent message
    count = db.query(func.count(Stay.id)).join(
        Conversation, Conversation.inquiry_id == Stay.inquiry_id, isouter=True
    ).filter(
        Stay.tenant_id == tenant_id,
        Stay.status == "confirmed",
        Stay.check_in >= today,
        Stay.check_in <= in_14d,
        or_(
            Conversation.last_message_at.is_(None),
            Conversation.last_message_at <= inactive_since,
        ),
    ).scalar() or 0

    if count >= 1:
        _upsert_insight(db, tenant_id, {
            "category_code": "A3",
            "category":      InsightCategory.URGENCY,
            "severity":      InsightSeverity.HIGH,
            "title":         f"{count} upcoming booking{'s' if count > 1 else ''} with no recent communication",
            "body":          "Send a check-in message to reduce no-show risk.",
            "cta_label":     "Send Check-in Message",
            "cta_href":      "/dashboard/inbox",
            "data_snapshot": {"count": count},
            "expires_at":    _NOW() + timedelta(hours=12),
        })
    else:
        _auto_resolve(db, tenant_id, "A3")


def detect_A4(db: Session, tenant_id: str) -> None:
    """A4: Missed calls never recovered by a callback within 24h -- Phase 2.5's
    calls.recovered_by_call_id (HAIP_Agent_Analytics_Dashboard_Plan_1.md
    #2.5.3), populated by call_ingest.py's _link_recovered_call(). 7-day
    lookback so this doesn't dredge up ancient unrecovered calls forever."""
    window_end = _NOW() - timedelta(hours=24)
    lookback_start = _NOW() - timedelta(days=7)

    count = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tenant_id,
        call_status_service.missed_call_sql_filter(),
        Call.recovered_by_call_id.is_(None),
        Call.callback_dismissed_at.is_(None),
        Call.created_at >= lookback_start,
        Call.created_at < window_end,
    ).scalar() or 0

    if count >= 1:
        _upsert_insight(db, tenant_id, {
            "category_code": "A4",
            "category":      InsightCategory.URGENCY,
            "severity":      InsightSeverity.HIGH,
            "title":         f"{count} missed call{'s' if count > 1 else ''} never called back",
            "body":          f"{count} missed call{'s' if count > 1 else ''} in the last 7 days with no follow-up call within 24 hours.",
            "cta_label":     "View Calls",
            "cta_href":      "/dashboard/calls?filter=missed",
            "data_snapshot": {"count": count},
            "expires_at":    _NOW() + timedelta(hours=6),
        })
    else:
        _auto_resolve(db, tenant_id, "A4")


# ─── CATEGORY B — Occupancy Warnings ─────────────────────────────────────────

def detect_B1(db: Session, tenant_id: str) -> None:
    """B1: Occupancy drop — next 7d projected occupancy < 70% of last 30d avg."""
    today = _NOW().date().isoformat()
    in_7d = (_NOW() + timedelta(days=7)).date().isoformat()
    ago_30d = (_NOW() - timedelta(days=30)).date().isoformat()

    # Confirmed stays next 7 days
    fwd = db.query(func.count(Stay.id)).filter(
        Stay.tenant_id == tenant_id,
        Stay.status.in_(["confirmed", "checked_in"]),
        Stay.check_in >= today,
        Stay.check_in <= in_7d,
    ).scalar() or 0

    # Confirmed stays last 30 days
    hist = db.query(func.count(Stay.id)).filter(
        Stay.tenant_id == tenant_id,
        Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
        Stay.check_in >= ago_30d,
        Stay.check_in <= today,
    ).scalar() or 0

    avg_per_week = hist / 4.3  # ≈ 30d / 7d
    threshold = avg_per_week * 0.7

    if avg_per_week > 0 and fwd < threshold:
        _upsert_insight(db, tenant_id, {
            "category_code": "B1",
            "category":      InsightCategory.OCCUPANCY,
            "severity":      InsightSeverity.MEDIUM,
            "title":         f"Occupancy dropping next week ({fwd} bookings vs avg {avg_per_week:.0f})",
            "body":          "Projected bookings for next 7 days are below historical average. Consider a promotion.",
            "cta_label":     "View Calendar",
            "cta_href":      "/dashboard/portfolio/calendar",
            "data_snapshot": {"fwd_stays": fwd, "avg_per_week": round(avg_per_week, 1)},
            "expires_at":    _NOW() + timedelta(days=1),
        })
    else:
        _auto_resolve(db, tenant_id, "B1")


def detect_B3(db: Session, tenant_id: str) -> None:
    """B3: Gap-fill opportunity — delegate to calendar suggestions engine."""
    # Lightweight version: count quoted inquiries with no recent follow-up
    cutoff = (_NOW() - timedelta(days=3)).isoformat()
    count = db.query(func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == tenant_id,
        Inquiry.stage == InquiryStage.QUOTED,
        Inquiry.quoted_at <= cutoff,
    ).scalar() or 0

    if count >= 3:
        _upsert_insight(db, tenant_id, {
            "category_code": "B3",
            "category":      InsightCategory.OCCUPANCY,
            "severity":      InsightSeverity.LOW,
            "title":         f"{count} quoted inquiries awaiting follow-up",
            "body":          "These inquiries were quoted 3+ days ago with no response. A nudge may convert them.",
            "cta_label":     "Follow Up",
            "cta_href":      "/dashboard/inquiries?stage=QUOTED",
            "data_snapshot": {"count": count},
            "expires_at":    _NOW() + timedelta(days=1),
        })
    else:
        _auto_resolve(db, tenant_id, "B3")


# ─── CATEGORY C — Revenue Opportunities ──────────────────────────────────────

def detect_C1(db: Session, tenant_id: str) -> None:
    """C1: High-value returning guests with no upcoming booking in 60 days."""
    ago_60d = (_NOW() - timedelta(days=60)).isoformat()

    from app.models.guest import Guest
    count = db.query(func.count(Guest.id)).filter(
        Guest.tenant_id == tenant_id,
        Guest.total_stays >= 2,
        Guest.last_contact_at <= ago_60d,
        Guest.marketing_consent == True,
    ).scalar() or 0

    if count >= 1:
        _upsert_insight(db, tenant_id, {
            "category_code": "C1",
            "category":      InsightCategory.REVENUE,
            "severity":      InsightSeverity.LOW,
            "title":         f"{count} repeat guest{'s' if count > 1 else ''} haven't been contacted in 60 days",
            "body":          "These guests have stayed before and consented to marketing. A personalised offer could re-engage them.",
            "cta_label":     "Send Offer",
            "cta_href":      "/dashboard/messaging/campaigns",
            "data_snapshot": {"count": count},
            "expires_at":    _NOW() + timedelta(days=7),
        })
    else:
        _auto_resolve(db, tenant_id, "C1")


def detect_C2(db: Session, tenant_id: str) -> None:
    """C2: Pipeline conversion push — quoted inquiries no follow-up in 3d."""
    cutoff = (_NOW() - timedelta(hours=72)).isoformat()
    count = db.query(func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == tenant_id,
        Inquiry.stage == InquiryStage.QUOTED,
        Inquiry.quoted_at <= cutoff,
    ).scalar() or 0

    total_value = db.query(func.sum(Inquiry.quoted_amount)).filter(
        Inquiry.tenant_id == tenant_id,
        Inquiry.stage == InquiryStage.QUOTED,
        Inquiry.quoted_at <= cutoff,
        Inquiry.quoted_amount.isnot(None),
    ).scalar() or 0

    if count >= 1:
        val_str = f" (₹{total_value/100000:.1f}L pipeline)" if total_value > 0 else ""
        _upsert_insight(db, tenant_id, {
            "category_code": "C2",
            "category":      InsightCategory.REVENUE,
            "severity":      InsightSeverity.MEDIUM,
            "title":         f"{count} quoted lead{'s' if count > 1 else ''} with no follow-up{val_str}",
            "body":          "Sent quotes 3+ days ago. A timely follow-up significantly improves close rate.",
            "cta_label":     "Follow Up",
            "cta_href":      "/dashboard/inquiries?stage=QUOTED",
            "data_snapshot": {"count": count, "pipeline_value": float(total_value)},
            "expires_at":    _NOW() + timedelta(hours=24),
        })
    else:
        _auto_resolve(db, tenant_id, "C2")


def detect_C3(db: Session, tenant_id: str) -> None:
    """C3: Underperforming property — occupancy < 50% of portfolio avg last 30d."""
    ago_30d = (_NOW() - timedelta(days=30)).date().isoformat()
    today   = _NOW().date().isoformat()

    # Stay counts per property for last 30 days
    rows = db.query(
        Stay.property_id,
        func.count(Stay.id).label("cnt"),
    ).filter(
        Stay.tenant_id == tenant_id,
        Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
        Stay.check_in >= ago_30d,
        Stay.check_in <= today,
    ).group_by(Stay.property_id).all()

    if not rows:
        _auto_resolve(db, tenant_id, "C3")
        return

    counts = [r.cnt for r in rows]
    avg = sum(counts) / len(counts)
    underperformers = [r.property_id for r in rows if r.cnt < avg * 0.5]

    if underperformers:
        # Get property names
        props = {str(p.id): p.name for p in db.query(Property).filter(
            Property.id.in_(underperformers)
        ).all()}
        names = ", ".join(props.get(pid, pid) for pid in underperformers[:3])
        extra = f" +{len(underperformers)-3} more" if len(underperformers) > 3 else ""
        _upsert_insight(db, tenant_id, {
            "category_code": "C3",
            "category":      InsightCategory.REVENUE,
            "severity":      InsightSeverity.MEDIUM,
            "title":         f"{'Properties' if len(underperformers) > 1 else 'Property'} underperforming: {names}{extra}",
            "body":          f"{len(underperformers)} {'properties' if len(underperformers) > 1 else 'property'} with < 50% of portfolio avg bookings this month.",
            "cta_label":     "View Analytics",
            "cta_href":      "/dashboard/analytics/properties",
            "data_snapshot": {"underperformers": underperformers, "portfolio_avg": round(avg, 1)},
            "expires_at":    _NOW() + timedelta(days=7),
        })
    else:
        _auto_resolve(db, tenant_id, "C3")


# ─── CATEGORY D — Quality & Compliance ───────────────────────────────────────

def detect_D3(db: Session, tenant_id: str) -> None:
    """D3: Integration health degraded -- an errored integration, or a stale polled PMS sync.

    Uses the same rule as the Integrations page and the Dashboard bar (integration_health), so the
    three can no longer disagree. A connected webhook channel with an old last_health_at is healthy.
    """
    from app.services import integration_health

    rows = db.query(Integration).filter(Integration.tenant_id == tenant_id).all()
    bad = [
        i for i in rows
        if integration_health.classify(i.kind, i.status, i.last_health_at, config=i.config)
        in (integration_health.RED, integration_health.YELLOW)
    ]

    if bad:
        names = ", ".join(i.kind for i in bad[:3])
        _upsert_insight(db, tenant_id, {
            "category_code": "D3",
            "category":      InsightCategory.QUALITY,
            "severity":      InsightSeverity.HIGH,
            "title":         f"Integration{'s' if len(bad) > 1 else ''} degraded: {names}",
            "body":          "One or more integrations are not healthy. This may affect data accuracy.",
            "cta_label":     "Reconnect",
            "cta_href":      "/dashboard/settings/integrations",
            "data_snapshot": {"integrations": [i.kind for i in bad]},
            "expires_at":    _NOW() + timedelta(hours=2),
        })
    else:
        _auto_resolve(db, tenant_id, "D3")


def detect_D4(db: Session, tenant_id: str) -> None:
    """D4: Agent AI-draft rejection rate spike -- >=40% rejected over the
    trailing 7 days, minimum 5 drafts to avoid noise on small samples.
    Uses Phase 2.5's ai_draft_outcomes.actor_user_id
    (HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.4). One insight per
    flagged agent (target_id = agent's user_id) -- Insight.target_id's own
    docstring already anticipates "agent_id" as a valid use, and unlike
    A1-A4's tenant-wide counts, this condition is inherently per-agent, so
    each agent's insight needs to resolve independently as their rate
    improves, not all-or-nothing with the rest.
    """
    from app.models.ai_draft_outcome import AIDraftOutcome
    from app.models.user import User

    _MIN_SAMPLE = 5
    _THRESHOLD = 0.4
    cutoff = (_NOW() - timedelta(days=7)).isoformat()

    rows = db.query(
        AIDraftOutcome.actor_user_id,
        func.count(AIDraftOutcome.id).label("total"),
        func.sum(case((AIDraftOutcome.outcome == "rejected", 1), else_=0)).label("rejected"),
    ).filter(
        AIDraftOutcome.tenant_id == tenant_id,
        AIDraftOutcome.actor_user_id.isnot(None),
        AIDraftOutcome.created_at >= cutoff,
    ).group_by(AIDraftOutcome.actor_user_id).all()

    flagged_agent_ids: set[str] = set()
    for row in rows:
        if row.total < _MIN_SAMPLE:
            continue
        rate = row.rejected / row.total
        if rate < _THRESHOLD:
            continue
        flagged_agent_ids.add(row.actor_user_id)
        agent = db.query(User).filter_by(id=row.actor_user_id, tenant_id=tenant_id).first()
        agent_name = agent.name if agent else "An agent"
        _upsert_insight(db, tenant_id, {
            "category_code": "D4",
            "target_id":     row.actor_user_id,
            "category":      InsightCategory.QUALITY,
            "severity":      InsightSeverity.MEDIUM,
            "title":         f"{agent_name}'s AI draft rejection rate is unusually high ({rate*100:.0f}%)",
            "body":          f"{row.rejected} of {row.total} AI drafts rejected in the last 7 days -- worth a quick check-in on draft quality or workflow.",
            "cta_label":     "Review Drafts",
            "cta_href":      "/dashboard/inbox",
            "data_snapshot": {"actor_user_id": row.actor_user_id, "total": row.total, "rejected": row.rejected, "rate": round(rate, 2)},
            "expires_at":    _NOW() + timedelta(days=1),
        })

    # Auto-resolve any agent previously flagged who's no longer over
    # threshold this run (including agents who dropped out of the grouped
    # rows entirely, e.g. no drafts at all in the trailing window).
    previously_active = db.query(Insight.target_id).filter(
        Insight.tenant_id == tenant_id,
        Insight.category_code == "D4",
        Insight.is_dismissed == False,
        Insight.is_auto_resolved == False,
    ).all()
    for (target_id,) in previously_active:
        if target_id not in flagged_agent_ids:
            _auto_resolve(db, tenant_id, "D4", target_id)


# ─── Run all ──────────────────────────────────────────────────────────────────

_DETECTORS = [
    detect_A1, detect_A2, detect_A3, detect_A4,
    detect_B1, detect_B3,
    detect_C1, detect_C2, detect_C3,
    detect_D3, detect_D4,
]


def run_all_detectors(db: Session, tenant_id: str) -> int:
    """
    Run every detector for a tenant and commit.
    Returns the number of active (non-dismissed) insights after the run.
    """
    for detector in _DETECTORS:
        try:
            detector(db, tenant_id)
        except Exception as exc:
            log.warning("Insight detector %s failed for tenant %s: %s", detector.__name__, tenant_id, exc)

    db.commit()

    return db.query(func.count(Insight.id)).filter(
        Insight.tenant_id == tenant_id,
        Insight.is_dismissed == False,
        Insight.is_auto_resolved == False,
    ).scalar() or 0
