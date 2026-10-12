"""
Custom Reports Engine
Owners/managers can select any combination of report type, date range,
metrics/columns, and filters — then preview or download as CSV.
"""

import copy
import csv
import io
import json
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case
from pydantic import BaseModel
from openpyxl import Workbook
from openpyxl.styles import Font
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.services.authz_service import has_capability
from app.models.user import User, UserRole
from app.models.call import Call, CallDirection, CallDisposition
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.guest import Guest
from app.models.score import CallScore
from app.models.conversation import Message, MessageDirection, MessageDeliveryState, ChannelType
from app.models.property import Stay
from app.core.audit import append_audit
from app.services import lead_report_service

router = APIRouter(prefix="/reports", tags=["reports"])

# ─── Report catalog ──────────────────────────────────────────────────────────

REPORT_CATALOG = [
    {
        "id": "calls",
        "name": "Call Intelligence",
        "description": "All calls with transcript status, QA scores, duration, disposition, and agent details.",
        "icon": "phone",
        "category": "Operations",
        "fields": [
            {"key": "date", "label": "Date", "default": True},
            {"key": "time", "label": "Time", "default": True},
            {"key": "direction", "label": "Direction", "default": True},
            {"key": "from_number", "label": "From Number", "default": True},
            {"key": "to_number", "label": "To Number", "default": False},
            {"key": "duration_seconds", "label": "Duration (s)", "default": True},
            {"key": "duration_formatted", "label": "Duration (mm:ss)", "default": False},
            {"key": "agent_name", "label": "Agent", "default": True},
            {"key": "disposition", "label": "Disposition", "default": True},
            {"key": "ai_score", "label": "QA Score", "default": True},
            {"key": "ai_summary", "label": "AI Summary", "default": False},
            {"key": "transcription_status", "label": "Transcript Status", "default": False},
            {"key": "ivr_provider", "label": "IVR Provider", "default": False},
            {"key": "guest_name", "label": "Guest Name", "default": False},
            {"key": "property_name", "label": "Property", "default": False},
        ],
        "filters": [
            {"key": "direction", "label": "Direction", "type": "select", "options": ["inbound", "outbound"]},
            {"key": "disposition", "label": "Disposition", "type": "select", "options": ["hot", "quoted", "booked", "lost", "callback", "no_answer", "voicemail"]},
            {"key": "min_score", "label": "Min QA Score", "type": "number"},
            {"key": "has_transcript", "label": "Has Transcript", "type": "boolean"},
        ],
    },
    lead_report_service.CATALOG_ENTRY,
    {
        "id": "guests",
        "name": "Guest Directory",
        "description": "Full guest list with contact details, stay history, and engagement metrics.",
        "icon": "users",
        "category": "CRM",
        "fields": [
            {"key": "name", "label": "Name", "default": True},
            {"key": "phone", "label": "Phone", "default": True},
            {"key": "email", "label": "Email", "default": True},
            {"key": "created_at", "label": "First Seen", "default": True},
            {"key": "last_contact", "label": "Last Contact", "default": False},
            {"key": "total_inquiries", "label": "Total Inquiries", "default": True},
            {"key": "total_stays", "label": "Total Stays", "default": True},
            {"key": "lifetime_value", "label": "Lifetime Value (₹)", "default": True},
            {"key": "tags", "label": "Tags", "default": False},
            {"key": "preferred_property", "label": "Preferred Property", "default": False},
            {"key": "nationality", "label": "Nationality", "default": False},
            {"key": "wa_opted_in", "label": "WA Opt-in", "default": False},
        ],
        "filters": [],
    },
    {
        "id": "qa_scores",
        "name": "QA & Agent Performance",
        "description": "Agent scorecards, per-criterion breakdown, and trend data.",
        "icon": "star",
        "category": "Intelligence",
        "fields": [
            {"key": "date", "label": "Date", "default": True},
            {"key": "agent_name", "label": "Agent", "default": True},
            {"key": "call_date", "label": "Call Date", "default": False},
            {"key": "total_score", "label": "Total Score", "default": True},
            {"key": "max_score", "label": "Max Score", "default": False},
            {"key": "score_pct", "label": "Score %", "default": True},
            {"key": "warm_greeting", "label": "Warm Greeting", "default": False},
            {"key": "needs_discovery", "label": "Needs Discovery", "default": False},
            {"key": "property_knowledge", "label": "Property Knowledge", "default": False},
            {"key": "objection_handling", "label": "Objection Handling", "default": False},
            {"key": "upsell_attempt", "label": "Upsell Attempt", "default": False},
            {"key": "dpdp_compliance", "label": "DPDP Compliance", "default": False},
            {"key": "overall_verdict", "label": "Verdict", "default": True},
            {"key": "coaching_flags", "label": "Coaching Flags", "default": False},
        ],
        "filters": [
            {"key": "min_score", "label": "Min Score %", "type": "number"},
            {"key": "verdict", "label": "Verdict", "type": "select", "options": ["pass", "review", "fail"]},
        ],
    },
    {
        "id": "revenue",
        "name": "Revenue & Bookings",
        "description": "Booking value, RevPAR, occupancy, and payment status from connected PMS.",
        "icon": "bar-chart",
        "category": "Revenue",
        "fields": [
            {"key": "booking_date", "label": "Booking Date", "default": True},
            {"key": "guest_name", "label": "Guest Name", "default": True},
            {"key": "property_name", "label": "Property", "default": True},
            {"key": "check_in", "label": "Check-in", "default": True},
            {"key": "check_out", "label": "Check-out", "default": True},
            {"key": "nights", "label": "Nights", "default": True},
            {"key": "pax", "label": "Pax", "default": False},
            {"key": "room_revenue", "label": "Room Revenue (₹)", "default": True},
            {"key": "total_revenue", "label": "Total Revenue (₹)", "default": True},
            {"key": "source", "label": "Booking Source", "default": True},
            {"key": "payment_status", "label": "Payment Status", "default": True},
            {"key": "commission", "label": "Commission (₹)", "default": False},
            {"key": "net_revenue", "label": "Net Revenue (₹)", "default": False},
        ],
        "filters": [
            {"key": "source", "label": "Booking Source", "type": "select", "options": ["direct", "ota_airbnb", "ota_booking", "ota_vrbo", "travel_agent"]},
            {"key": "payment_status", "label": "Payment Status", "type": "select", "options": ["paid", "partial", "pending", "refunded"]},
        ],
    },
    {
        "id": "whatsapp",
        "name": "WhatsApp & Messaging",
        "description": "Message delivery, read rates, campaign performance, and opt-in trends.",
        "icon": "message-square",
        "category": "Messaging",
        "fields": [
            {"key": "date", "label": "Date", "default": True},
            {"key": "campaign_name", "label": "Campaign", "default": True},
            {"key": "template_name", "label": "Template", "default": True},
            {"key": "sent", "label": "Sent", "default": True},
            {"key": "delivered", "label": "Delivered", "default": True},
            {"key": "read", "label": "Read", "default": True},
            {"key": "failed", "label": "Failed", "default": True},
            {"key": "delivery_rate", "label": "Delivery Rate %", "default": True},
            {"key": "read_rate", "label": "Read Rate %", "default": True},
            {"key": "opt_outs", "label": "Opt-outs", "default": False},
            {"key": "replies", "label": "Replies", "default": False},
        ],
        "filters": [],
    },
    {
        "id": "team",
        "name": "Team Activity",
        "description": "Per-agent call volume, response times, QA averages, and activity log.",
        "icon": "users",
        "category": "Operations",
        "fields": [
            {"key": "agent_name", "label": "Agent", "default": True},
            {"key": "role", "label": "Role", "default": True},
            {"key": "calls_handled", "label": "Calls Handled", "default": True},
            {"key": "avg_call_duration", "label": "Avg Duration (s)", "default": True},
            {"key": "avg_qa_score", "label": "Avg QA Score", "default": True},
            {"key": "inquiries_handled", "label": "Inquiries Handled", "default": True},
            {"key": "messages_sent", "label": "Messages Sent", "default": False},
            {"key": "conversion_rate", "label": "Conversion Rate %", "default": False},
            {"key": "last_active", "label": "Last Active", "default": False},
        ],
        "filters": [],
    },
]


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    report_id: str
    fields: List[str]
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    filters: Optional[Dict[str, Any]] = {}
    limit: int = 500


# ─── Data fetchers ────────────────────────────────────────────────────────────

def _date_range(date_from: Optional[str], date_to: Optional[str]):
    now = datetime.now(timezone.utc)
    df = datetime.fromisoformat(date_from) if date_from else (now - timedelta(days=30))
    dt = datetime.fromisoformat(date_to) if date_to else now
    # The frontend's date pickers send bare "YYYY-MM-DD" (no time component).
    # fromisoformat() parses that as midnight at the *start* of that day, so
    # every fetcher's `created_at <= date_to` filter silently excluded
    # everything from today except rows created at exactly 00:00:00 --
    # e.g. picking "today" as the end date returned zero of today's rows.
    # Bump a bare date to the end of that day so it's actually inclusive.
    if date_to and len(date_to) <= 10:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return df.isoformat(), dt.isoformat()


def _fmt_date(value) -> str:
    """created_at is a real DateTime column (TimestampMixin) on Guest/Inquiry/
    CallScore, but a plain ISO string column on Call.started_at -- handle
    both so callers don't need to know which one they've got."""
    if not value:
        return ""
    if isinstance(value, str):
        return value[:10]
    return value.strftime("%Y-%m-%d")


def fetch_calls(
    db: Session, tenant_id: str, req: ReportRequest, scope_user_id: Optional[str] = None,
) -> List[Dict]:
    date_from, date_to = _date_range(req.date_from, req.date_to)
    q = db.query(Call).filter(
        Call.tenant_id == tenant_id,
        Call.started_at >= date_from,
        Call.started_at <= date_to,
    )
    filters = req.filters or {}
    if filters.get("direction"):
        q = q.filter(Call.direction == filters["direction"])
    if filters.get("disposition"):
        q = q.filter(
            or_(Call.human_disposition == filters["disposition"],
                Call.ai_disposition == filters["disposition"])
        )
    if filters.get("min_score"):
        q = q.filter(Call.ai_score >= float(filters["min_score"]))
    if scope_user_id:
        q = q.filter(Call.agent_id == scope_user_id)
    has_transcript = str(filters.get("has_transcript", "")).lower()
    if has_transcript in ("true", "1", "yes"):
        q = q.filter(Call.transcription_status == "done")
    elif has_transcript in ("false", "0", "no"):
        q = q.filter(or_(Call.transcription_status.is_(None), Call.transcription_status != "done"))
    calls = q.order_by(Call.started_at.desc(), Call.id).limit(req.limit).all()

    rows = []
    for c in calls:
        dur = c.duration_seconds or 0
        disp = (c.human_disposition or c.ai_disposition or "pending")
        if hasattr(disp, "value"):
            disp = disp.value
        row: Dict[str, Any] = {
            "date": c.started_at[:10] if c.started_at else "",
            "time": c.started_at[11:19] if c.started_at else "",
            "direction": c.direction.value if hasattr(c.direction, "value") else str(c.direction),
            "from_number": c.from_number or "",
            "to_number": c.to_number or "",
            "duration_seconds": dur,
            "duration_formatted": f"{dur // 60}:{str(dur % 60).zfill(2)}",
            "agent_name": c.agent.name if c.agent else "",
            "disposition": disp,
            "ai_score": float(c.ai_score) if c.ai_score else "",
            "ai_summary": c.ai_summary or "",
            "transcription_status": c.transcription_status or "",
            "ivr_provider": c.ivr_provider or "",
            "guest_name": c.guest.name if c.guest else "",
            "property_name": "",
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def _lead_report(db: Session, tenant_id: str, req: ReportRequest, scope_user_id: Optional[str] = None):
    """The leads report lives in lead_report_service; this only turns a bad
    filter into a 422 instead of a wrong list."""
    try:
        filters = lead_report_service.parse_filters(req.filters, req.date_from, req.date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return lead_report_service.build_lead_report(
        db, tenant_id, filters, req.fields, scope_user_id=scope_user_id, limit=req.limit,
    )


def fetch_inquiries(
    db: Session, tenant_id: str, req: ReportRequest, scope_user_id: Optional[str] = None,
) -> List[Dict]:
    return _lead_report(db, tenant_id, req, scope_user_id).rows


def fetch_guests(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    date_from, date_to = _date_range(req.date_from, req.date_to)
    guests = db.query(Guest).filter(
        Guest.tenant_id == tenant_id,
        Guest.created_at >= date_from,
    ).order_by(Guest.created_at.desc()).limit(req.limit).all()

    rows = []
    for g in guests:
        row: Dict[str, Any] = {
            "name": g.name or "",
            "phone": g.phone or "",
            "email": g.email or "",
            "created_at": _fmt_date(g.created_at),
            "last_contact": _fmt_date(g.last_contact_at),
            "total_inquiries": g.total_inquiries or 0,  # denormalized counter, not a live count -- avoids N+1
            "total_stays": g.total_stays or 0,
            "lifetime_value": float(g.lifetime_value) if g.lifetime_value else "",
            "tags": ", ".join(g.tags or []),
            "preferred_property": "",
            "nationality": g.nationality or "",
            "wa_opted_in": "",
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def fetch_qa_scores(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    date_from, date_to = _date_range(req.date_from, req.date_to)
    q = db.query(CallScore).join(Call, CallScore.call_id == Call.id).filter(
        Call.tenant_id == tenant_id,
        Call.started_at >= date_from,
        Call.started_at <= date_to,
    )
    filters = req.filters or {}
    if filters.get("min_score"):
        q = q.filter(CallScore.percentage >= float(filters["min_score"]))
    scores = q.order_by(Call.started_at.desc()).limit(req.limit).all()

    rows = []
    for s in scores:
        call = s.call
        # criterion_scores is [{criterion_id, score, evidence_span, confidence}, ...]
        # against a tenant-defined rubric -- not a fixed set of named criteria,
        # so look each expected id up by key rather than assuming it's present.
        criteria = {c.get("criterion_id"): c.get("score") for c in (s.criterion_scores or [])}
        pct = float(s.percentage) if s.percentage is not None else 0.0
        # No stored pass/review/fail verdict on CallScore -- derive one so the
        # "Verdict" column/filter isn't just blank. 80%/60% are heuristic
        # thresholds, not a stored business rule.
        if s.has_auto_fail:
            verdict = "fail"
        elif pct >= 80:
            verdict = "pass"
        elif pct >= 60:
            verdict = "review"
        else:
            verdict = "fail"
        if filters.get("verdict") and verdict != filters["verdict"]:
            continue
        row: Dict[str, Any] = {
            "date": _fmt_date(s.created_at),
            "agent_name": call.agent.name if call and call.agent else "",
            "call_date": _fmt_date(call.started_at) if call else "",
            "total_score": float(s.total_score or 0),
            "max_score": float(s.max_score or 0),
            "score_pct": pct,
            "warm_greeting": criteria.get("warm_greeting", ""),
            "needs_discovery": criteria.get("needs_discovery", ""),
            "property_knowledge": criteria.get("property_knowledge", ""),
            "objection_handling": criteria.get("objection_handling", ""),
            "upsell_attempt": criteria.get("upsell_attempt", ""),
            "dpdp_compliance": criteria.get("dpdp_compliance", ""),
            "overall_verdict": verdict,
            "coaching_flags": "",  # not tracked on CallScore yet
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def fetch_team(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    """Team performance report — single aggregate query per metric, no per-user N+1."""
    from app.models.user import User as UserModel
    date_from, date_to = _date_range(req.date_from, req.date_to)

    # Single aggregate query for call stats per agent
    call_stats = db.query(
        Call.agent_id,
        func.count(Call.id).label("calls_count"),
        func.avg(Call.duration_seconds).label("avg_dur"),
        func.avg(Call.ai_score).label("avg_score"),
    ).filter(
        Call.tenant_id == tenant_id,
        Call.started_at >= date_from,
        Call.started_at <= date_to,
    ).group_by(Call.agent_id).all()

    stats_map = {
        r.agent_id: {
            "calls_count": r.calls_count or 0,
            "avg_dur": float(r.avg_dur) if r.avg_dur else 0.0,
            "avg_score": float(r.avg_score) if r.avg_score else None,
        }
        for r in call_stats
    }

    users = db.query(UserModel).filter_by(tenant_id=tenant_id, is_deleted=False, is_active=True).all()
    rows = []
    for u in users:
        s = stats_map.get(u.id, {"calls_count": 0, "avg_dur": 0.0, "avg_score": None})
        row: Dict[str, Any] = {
            "agent_name": u.name,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "calls_handled": s["calls_count"],
            "avg_call_duration": round(s["avg_dur"], 1),
            "avg_qa_score": round(s["avg_score"], 1) if s["avg_score"] is not None else "",
            "inquiries_handled": 0,   # loaded below in batch
            "messages_sent": 0,
            "conversion_rate": "",
            "last_active": "",
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def fetch_whatsapp(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    """Daily WhatsApp send/delivery aggregate from real Message rows.
    There's no Campaign/Template model in the schema yet, so campaign_name
    and template_name are left blank rather than fabricated -- everything
    else here is a real count off Message.delivery_state."""
    date_from, date_to = _date_range(req.date_from, req.date_to)
    day = func.date(Message.created_at)
    sent_case = case((Message.direction == MessageDirection.OUTBOUND, 1))
    delivered_case = case((and_(
        Message.direction == MessageDirection.OUTBOUND,
        Message.delivery_state.in_([MessageDeliveryState.DELIVERED, MessageDeliveryState.READ]),
    ), 1))
    read_case = case((and_(
        Message.direction == MessageDirection.OUTBOUND,
        Message.delivery_state == MessageDeliveryState.READ,
    ), 1))
    failed_case = case((and_(
        Message.direction == MessageDirection.OUTBOUND,
        Message.delivery_state.in_([MessageDeliveryState.FAILED, MessageDeliveryState.REJECTED]),
    ), 1))
    replies_case = case((Message.direction == MessageDirection.INBOUND, 1))

    daily = db.query(
        day.label("day"),
        func.count(sent_case).label("sent"),
        func.count(delivered_case).label("delivered"),
        func.count(read_case).label("read"),
        func.count(failed_case).label("failed"),
        func.count(replies_case).label("replies"),
    ).filter(
        Message.tenant_id == tenant_id,
        Message.channel == ChannelType.WHATSAPP,
        Message.is_internal.is_(False),
        Message.created_at >= date_from,
        Message.created_at <= date_to,
    ).group_by(day).order_by(day.desc()).limit(req.limit).all()

    rows = []
    for r in daily:
        sent = r.sent or 0
        delivered = r.delivered or 0
        read = r.read or 0
        row: Dict[str, Any] = {
            "date": r.day.isoformat() if hasattr(r.day, "isoformat") else str(r.day),
            "campaign_name": "",
            "template_name": "",
            "sent": sent,
            "delivered": delivered,
            "read": read,
            "failed": r.failed or 0,
            "delivery_rate": round(delivered / sent * 100, 1) if sent else 0,
            "read_rate": round(read / sent * 100, 1) if sent else 0,
            "opt_outs": 0,  # not tracked yet
            "replies": r.replies or 0,
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def fetch_revenue(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    date_from, date_to = _date_range(req.date_from, req.date_to)
    q = db.query(Stay).filter(
        Stay.tenant_id == tenant_id,
        Stay.created_at >= date_from,
        Stay.created_at <= date_to,
    )
    filters = req.filters or {}
    if filters.get("source"):
        q = q.filter(Stay.channel_source == filters["source"])
    stays = q.order_by(Stay.created_at.desc()).limit(req.limit).all()

    rows = []
    for s in stays:
        nights = (s.check_out - s.check_in).days if s.check_in and s.check_out else 0
        amount = float(s.total_amount) if s.total_amount else 0.0
        row: Dict[str, Any] = {
            "booking_date": _fmt_date(s.created_at),
            "guest_name": s.guest.name if s.guest else "",
            "property_name": s.property.name if s.property else "",
            "check_in": s.check_in.isoformat() if s.check_in else "",
            "check_out": s.check_out.isoformat() if s.check_out else "",
            "nights": nights,
            "pax": (s.adults or 0) + (s.children or 0),
            "room_revenue": amount,
            "total_revenue": amount,
            "source": s.channel_source or "direct",
            "payment_status": "",  # not tracked on Stay yet
            "commission": "",      # not tracked on Stay yet
            "net_revenue": "",     # not tracked on Stay yet
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def fetch_report_data(
    db: Session, tenant_id: str, req: ReportRequest, scope_user_id: Optional[str] = None,
) -> List[Dict]:
    if req.report_id == "calls":
        return fetch_calls(db, tenant_id, req, scope_user_id)
    elif req.report_id == "inquiries":
        return fetch_inquiries(db, tenant_id, req, scope_user_id)
    elif req.report_id == "guests":
        return fetch_guests(db, tenant_id, req)
    elif req.report_id == "qa_scores":
        return fetch_qa_scores(db, tenant_id, req)
    elif req.report_id == "team":
        return fetch_team(db, tenant_id, req)
    elif req.report_id == "whatsapp":
        return fetch_whatsapp(db, tenant_id, req)
    elif req.report_id == "revenue":
        return fetch_revenue(db, tenant_id, req)
    else:
        return []


def run_report(
    db: Session, tenant_id: str, req: ReportRequest, scope_user_id: Optional[str] = None,
):
    """(rows, total, truncated). `total` is the exact match count where the
    report can give one cheaply (leads), otherwise None."""
    if req.report_id == "inquiries":
        rep = _lead_report(db, tenant_id, req, scope_user_id)
        return rep.rows, rep.total, rep.truncated
    rows = fetch_report_data(db, tenant_id, req, scope_user_id)
    return rows, None, len(rows) >= req.limit >= MAX_DOWNLOAD_ROWS


# ─── Who can run what ─────────────────────────────────────────────────────────

MAX_DOWNLOAD_ROWS = lead_report_service.MAX_ROWS
PREVIEW_ROWS = 50

FULL_ACCESS_ROLES = (UserRole.OWNER, UserRole.MANAGER, UserRole.COMPLIANCE)
# Sales agents can download the lead and call reports -- their own only.
AGENT_ROLES = (UserRole.CONCIERGE, UserRole.RESERVATIONS)
AGENT_REPORTS = ("inquiries", "calls")


def _allowed_reports(user: User) -> Optional[tuple]:
    """None = every report. Otherwise the report ids this role may run."""
    if user.role in FULL_ACCESS_ROLES:
        return None
    if user.role in AGENT_ROLES:
        return AGENT_REPORTS
    return ()


def _catalog_entry(report_id: str) -> Dict[str, Any]:
    entry = next((r for r in REPORT_CATALOG if r["id"] == report_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    return entry


def _report_scope(user: User, report_id: str) -> Optional[str]:
    """Whose data the report is limited to: None = the whole workspace, a user
    id = only that person's leads and calls. 403 if the role can't run it."""
    allowed = _allowed_reports(user)
    if allowed is None:
        return None
    if report_id in allowed:
        return user.id
    raise HTTPException(status_code=403, detail="Your role can't run this report")


MONEY_REPORTS = ("revenue",)   # per-booking value: needs revenue.read on top of the role's report access


def _require_report_money(db: Session, user: User, report_id: str) -> None:
    """403 for a revenue report without revenue.read, whatever the role's report access says (compliance can run
    most reports but holds no revenue capability by default)."""
    if report_id in MONEY_REPORTS and not has_capability(db, user, "revenue.read"):
        raise HTTPException(status_code=403, detail="Your role can't run this report")


def _catalog_for(db: Session, user: User) -> List[Dict[str, Any]]:
    """The catalog this person sees: only their reports, with the workspace's
    own stages and owners filled into the filter choices."""
    allowed = _allowed_reports(user)
    options = lead_report_service.resolve_options(db, user.tenant_id)
    out = []
    for entry in REPORT_CATALOG:
        if allowed is not None and entry["id"] not in allowed:
            continue
        if entry["id"] in MONEY_REPORTS and not has_capability(db, user, "revenue.read"):
            continue
        item = copy.deepcopy(entry)
        filters = []
        for flt in item.get("filters", []):
            if allowed is not None and flt["key"] == "owner":
                continue          # an agent's report is already just theirs
            opts = flt.get("options")
            if isinstance(opts, str) and opts.startswith("@"):
                flt["options"] = options.get(opts, [])
            filters.append(flt)
        item["filters"] = filters
        out.append(item)
    return out


def _clean_fields(entry: Dict[str, Any], fields: List[str]) -> List[str]:
    known = {f["key"] for f in entry["fields"]}
    kept = [f for f in fields if f in known]
    if not kept:
        raise HTTPException(status_code=422, detail="Pick at least one column")
    return kept


# ─── Building the file ────────────────────────────────────────────────────────

# A guest types their own name, and an agent opens the file in Excel: a name
# like =HYPERLINK(...) would run as a formula. Text starting with a formula
# character gets a leading apostrophe -- except the shapes we *expect* to start
# with one: a +91 phone number and an @instagram handle.
_EXPECTED_LEADING = re.compile(r"^(\+\d[\d ()-]{5,}|@[\w.]{1,64}|-?\d+(\.\d+)?)$")


def _safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value and value[0] in "=+-@\t\r" and not _EXPECTED_LEADING.match(value):
        return "'" + value
    return value


def _build_xlsx(fields: List[str], field_labels: Dict[str, str], rows: List[Dict], sheet_name: str) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31] or "Report"
    ws.append([field_labels.get(f, f) for f in fields])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for row in rows:
        ws.append([_safe_cell(row.get(f, "")) for f in fields])
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(width + 2, 40)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _render(
    fmt: str, fields: List[str], entry: Dict[str, Any], rows: List[Dict],
    total: Optional[int], truncated: bool,
) -> StreamingResponse:
    labels = {f["key"]: f["label"] for f in entry["fields"]}
    name = entry["name"].replace(" ", "_").lower()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"haip_{name}_{stamp}"
    disposition = {"Content-Disposition": f'attachment; filename="{filename}.{fmt}"'}

    if fmt == "json":
        content = json.dumps({
            "report": name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "row_count": len(rows),
            "total": total,
            "truncated": truncated,
            "data": rows,
        }, default=str, indent=2)
        return StreamingResponse(io.StringIO(content), media_type="application/json", headers=disposition)

    if fmt == "xlsx":
        return StreamingResponse(
            _build_xlsx(fields, labels, rows, entry["name"]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=disposition,
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([labels.get(f, f) for f in fields])
    for row in rows:
        writer.writerow([_safe_cell(row.get(f, "")) for f in fields])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers=disposition)


def _audit_download(
    db: Session, user: User, body: ReportRequest, fmt: str,
    rows: List[Dict], total: Optional[int], truncated: bool, scope: Optional[str],
) -> None:
    """A report can carry guests' phone numbers, so every download is on the
    audit trail: who, which report, what they asked for, how many rows."""
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="reports.download",
        actor_user_id=user.id,
        target_type="report",
        target_id=body.report_id,
        payload={
            "format": fmt,
            "fields": body.fields,
            "filters": body.filters or {},
            "date_from": body.date_from,
            "date_to": body.date_to,
            "row_count": len(rows),
            "total": total,
            "truncated": truncated,
            "scope": "own" if scope else "workspace",
        },
    )
    db.commit()


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_report_catalog(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _catalog_for(db, current_user)


@router.post("/preview")
def preview_report(
    body: ReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The first few rows, plus how many rows the full report would hold."""
    entry = _catalog_entry(body.report_id)
    scope = _report_scope(current_user, body.report_id)
    _require_report_money(db, current_user, body.report_id)
    fields = _clean_fields(entry, body.fields)
    req = body.model_copy(update={"fields": fields, "limit": max(1, min(body.limit, PREVIEW_ROWS))})
    rows, total, truncated = run_report(db, current_user.tenant_id, req, scope)
    return {
        "report_id": body.report_id,
        "report_name": entry["name"],
        "row_count": len(rows),
        "total": total,
        "truncated": truncated,
        "scope": "own" if scope else "workspace",
        "columns": fields,
        "rows": rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/download")
def download_report(
    body: ReportRequest,
    format: str = Query(default="csv", pattern="^(csv|json|xlsx)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The full report as CSV, JSON or Excel -- every matching row, up to
    MAX_DOWNLOAD_ROWS, and the audit trail says how many."""
    entry = _catalog_entry(body.report_id)
    scope = _report_scope(current_user, body.report_id)
    _require_report_money(db, current_user, body.report_id)
    fields = _clean_fields(entry, body.fields)
    req = body.model_copy(update={"fields": fields, "limit": MAX_DOWNLOAD_ROWS})
    rows, total, truncated = run_report(db, current_user.tenant_id, req, scope)
    _audit_download(db, current_user, req, format, rows, total, truncated, scope)
    return _render(format, fields, entry, rows, total, truncated)


@router.get("/export")
def export_report(
    report_id: str = Query(...),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    format: str = Query(default="csv", pattern="^(csv|json|xlsx)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GET form of /download with the report's default columns and no
    filters -- for a plain link. Same access rules and audit as /download."""
    entry = _catalog_entry(report_id)
    scope = _report_scope(current_user, report_id)
    _require_report_money(db, current_user, report_id)
    fields = [f["key"] for f in entry["fields"] if f.get("default")]
    body = ReportRequest(
        report_id=report_id,
        fields=fields,
        date_from=(date_from or "")[:10] or None,
        date_to=(date_to or "")[:10] or None,
        limit=MAX_DOWNLOAD_ROWS,
    )
    rows, total, truncated = run_report(db, current_user.tenant_id, body, scope)
    _audit_download(db, current_user, body, format, rows, total, truncated, scope)
    return _render(format, fields, entry, rows, total, truncated)


# ─── Aggregate/chart reports ────────────────────────────────────────────────
# Unlike the row-export catalog above, these return pre-aggregated series for
# chart rendering. Auth matches the rest of this file (OWNER/MANAGER/COMPLIANCE).

@router.get("/lead-source-breakdown")
def get_lead_source_breakdown(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.COMPLIANCE)),
):
    from app.services.leads_service import get_source_breakdown
    df, dt = _date_range(date_from, date_to)
    rows = get_source_breakdown(db, current_user.tenant_id, datetime.fromisoformat(df), datetime.fromisoformat(dt))
    return {"date_from": df, "date_to": dt, "sources": rows}


@router.get("/lead-funnel-daily")
def get_lead_funnel_daily(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.COMPLIANCE)),
):
    from app.services.leads_service import get_daily_lead_funnel
    df, dt = _date_range(date_from, date_to)
    rows = get_daily_lead_funnel(db, current_user.tenant_id, datetime.fromisoformat(df), datetime.fromisoformat(dt))
    return {"date_from": df, "date_to": dt, "daily": rows}


@router.get("/occupancy-summary")
def get_reports_occupancy_summary(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.COMPLIANCE)),
):
    """Thin wrapper around calendar.py's occupancy grid aggregation so this
    report sits alongside the others under /reports for the frontend."""
    from app.api.v1.endpoints.calendar import get_occupancy_summary
    df, dt = _date_range(date_from, date_to)
    from_d = datetime.fromisoformat(df).date().isoformat()
    to_d = datetime.fromisoformat(dt).date().isoformat()
    return get_occupancy_summary(from_date=from_d, to_date=to_d, db=db, current_user=current_user)
