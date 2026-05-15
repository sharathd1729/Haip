"""
Custom Reports Engine
Owners/managers can select any combination of report type, date range,
metrics/columns, and filters — then preview or download as CSV.
"""

import csv
import io
import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from pydantic import BaseModel
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.call import Call, CallDirection, CallDisposition
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.guest import Guest
from app.models.score import CallScore
from app.models.conversation import Message

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
    {
        "id": "inquiries",
        "name": "Inquiry Pipeline",
        "description": "Lead funnel with source, stage, value, and conversion metrics.",
        "icon": "zap",
        "category": "CRM",
        "fields": [
            {"key": "created_at", "label": "Created Date", "default": True},
            {"key": "guest_name", "label": "Guest Name", "default": True},
            {"key": "guest_phone", "label": "Phone", "default": True},
            {"key": "source", "label": "Source", "default": True},
            {"key": "stage", "label": "Stage", "default": True},
            {"key": "check_in", "label": "Check-in Date", "default": True},
            {"key": "check_out", "label": "Check-out Date", "default": True},
            {"key": "nights", "label": "Nights", "default": False},
            {"key": "pax", "label": "Pax (Guests)", "default": False},
            {"key": "budget", "label": "Budget", "default": False},
            {"key": "quoted_amount", "label": "Quoted Amount", "default": True},
            {"key": "lost_reason", "label": "Lost Reason", "default": False},
            {"key": "property_name", "label": "Property", "default": False},
            {"key": "tags", "label": "Tags", "default": False},
        ],
        "filters": [
            {"key": "stage", "label": "Stage", "type": "select", "options": ["new", "responding", "quoted", "site_visit", "booked", "lost", "ghosted"]},
            {"key": "source", "label": "Source", "type": "select", "options": ["website", "google", "meta_ig", "meta_fb", "click_to_wa", "wa_direct", "email", "phone", "walk_in", "referral", "travel_agent", "ota_airbnb", "ota_booking"]},
        ],
    },
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
    return df.isoformat(), dt.isoformat()


def fetch_calls(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
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
    calls = q.order_by(Call.started_at.desc()).limit(req.limit).all()

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


def fetch_inquiries(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    date_from, date_to = _date_range(req.date_from, req.date_to)
    q = db.query(Inquiry).filter(
        Inquiry.tenant_id == tenant_id,
        Inquiry.created_at >= date_from,
        Inquiry.created_at <= date_to,
    )
    filters = req.filters or {}
    if filters.get("stage"):
        q = q.filter(Inquiry.stage == filters["stage"])
    if filters.get("source"):
        q = q.filter(Inquiry.source == filters["source"])
    inquiries = q.order_by(Inquiry.created_at.desc()).limit(req.limit).all()

    rows = []
    for inq in inquiries:
        nights = 0
        if inq.check_in and inq.check_out:
            try:
                nights = (datetime.fromisoformat(inq.check_out) - datetime.fromisoformat(inq.check_in)).days
            except Exception:
                pass
        row: Dict[str, Any] = {
            "created_at": inq.created_at[:10] if inq.created_at else "",
            "guest_name": inq.guest.name if inq.guest else "",
            "guest_phone": inq.guest.phone if inq.guest else "",
            "source": inq.source.value if hasattr(inq.source, "value") else str(inq.source or ""),
            "stage": inq.stage.value if hasattr(inq.stage, "value") else str(inq.stage or ""),
            "check_in": inq.check_in or "",
            "check_out": inq.check_out or "",
            "nights": nights,
            "pax": inq.pax or "",
            "budget": inq.budget or "",
            "quoted_amount": inq.quoted_amount or "",
            "lost_reason": inq.lost_reason.value if hasattr(inq.lost_reason, "value") else str(inq.lost_reason or ""),
            "property_name": "",
            "tags": ", ".join(inq.tags or []),
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


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
            "created_at": g.created_at[:10] if g.created_at else "",
            "last_contact": "",
            "total_inquiries": len(g.inquiries) if hasattr(g, "inquiries") else 0,
            "total_stays": 0,
            "lifetime_value": float(g.lifetime_value) if hasattr(g, "lifetime_value") and g.lifetime_value else "",
            "tags": ", ".join(g.tags or []),
            "preferred_property": "",
            "nationality": g.nationality or "",
            "wa_opted_in": "",
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def fetch_qa_scores(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    date_from, date_to = _date_range(req.date_from, req.date_to)
    scores = db.query(CallScore).join(Call, CallScore.call_id == Call.id).filter(
        Call.tenant_id == tenant_id,
        Call.started_at >= date_from,
        Call.started_at <= date_to,
    ).order_by(Call.started_at.desc()).limit(req.limit).all()

    rows = []
    for s in scores:
        call = s.call
        criteria = s.criteria_scores or {}
        max_pts = s.max_score or 100
        pct = round((float(s.total_score or 0) / max_pts) * 100, 1) if max_pts else 0
        row: Dict[str, Any] = {
            "date": s.created_at[:10] if s.created_at else "",
            "agent_name": call.agent.name if call and call.agent else "",
            "call_date": call.started_at[:10] if call and call.started_at else "",
            "total_score": float(s.total_score or 0),
            "max_score": max_pts,
            "score_pct": pct,
            "warm_greeting": criteria.get("warm_greeting", ""),
            "needs_discovery": criteria.get("needs_discovery", ""),
            "property_knowledge": criteria.get("property_knowledge", ""),
            "objection_handling": criteria.get("objection_handling", ""),
            "upsell_attempt": criteria.get("upsell_attempt", ""),
            "dpdp_compliance": criteria.get("dpdp_compliance", ""),
            "overall_verdict": s.verdict or "",
            "coaching_flags": ", ".join(s.coaching_flags or []),
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def fetch_team(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    from app.models.user import User as UserModel
    date_from, date_to = _date_range(req.date_from, req.date_to)
    users = db.query(UserModel).filter_by(tenant_id=tenant_id, is_deleted=False, is_active=True).all()
    rows = []
    for u in users:
        calls_count = db.query(func.count(Call.id)).filter(
            Call.tenant_id == tenant_id,
            Call.agent_id == u.id,
            Call.started_at >= date_from,
            Call.started_at <= date_to,
        ).scalar() or 0

        avg_dur = db.query(func.avg(Call.duration_seconds)).filter(
            Call.tenant_id == tenant_id, Call.agent_id == u.id
        ).scalar()

        avg_score = db.query(func.avg(Call.ai_score)).filter(
            Call.tenant_id == tenant_id, Call.agent_id == u.id, Call.ai_score.isnot(None)
        ).scalar()

        inq_count = db.query(func.count(Inquiry.id)).filter(
            Inquiry.tenant_id == tenant_id,
            Inquiry.created_at >= date_from,
        ).scalar() or 0

        row: Dict[str, Any] = {
            "agent_name": u.name,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "calls_handled": calls_count,
            "avg_call_duration": round(float(avg_dur), 1) if avg_dur else 0,
            "avg_qa_score": round(float(avg_score), 1) if avg_score else "",
            "inquiries_handled": inq_count,
            "messages_sent": 0,
            "conversion_rate": "",
            "last_active": "",
        }
        rows.append({k: row[k] for k in req.fields if k in row})
    return rows


def fetch_report_data(db: Session, tenant_id: str, req: ReportRequest) -> List[Dict]:
    if req.report_id == "calls":
        return fetch_calls(db, tenant_id, req)
    elif req.report_id == "inquiries":
        return fetch_inquiries(db, tenant_id, req)
    elif req.report_id == "guests":
        return fetch_guests(db, tenant_id, req)
    elif req.report_id == "qa_scores":
        return fetch_qa_scores(db, tenant_id, req)
    elif req.report_id == "team":
        return fetch_team(db, tenant_id, req)
    else:
        # revenue / whatsapp — return empty for now (requires PMS/WA integration data)
        return []


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_report_catalog(current_user: User = Depends(get_current_user)):
    return REPORT_CATALOG


@router.post("/preview")
def preview_report(
    body: ReportRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    """Return up to 50 rows for preview in the UI."""
    preview_req = ReportRequest(**body.model_dump())
    preview_req.limit = 50
    rows = fetch_report_data(db, current_user.tenant_id, preview_req)
    catalog_item = next((r for r in REPORT_CATALOG if r["id"] == body.report_id), None)
    return {
        "report_id": body.report_id,
        "report_name": catalog_item["name"] if catalog_item else body.report_id,
        "row_count": len(rows),
        "columns": body.fields,
        "rows": rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/download")
def download_report(
    body: ReportRequest,
    format: str = Query(default="csv", regex="^(csv|json)$"),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    """Stream the full report as CSV or JSON download."""
    rows = fetch_report_data(db, current_user.tenant_id, body)
    catalog_item = next((r for r in REPORT_CATALOG if r["id"] == body.report_id), None)
    report_name = (catalog_item["name"] if catalog_item else body.report_id).replace(" ", "_").lower()
    date_suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"haip_{report_name}_{date_suffix}"

    if format == "json":
        content = json.dumps({
            "report": report_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "row_count": len(rows),
            "data": rows,
        }, default=str, indent=2)
        return StreamingResponse(
            io.StringIO(content),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    # CSV
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=body.fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write(",".join(body.fields) + "\n")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
