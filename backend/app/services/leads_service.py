"""
Leads360 Service — Query engine for the pipeline view.

Handles:
  - Paginated pipeline query (one row per inquiry)
  - Profile completeness computation
  - Property interest extraction from call AI analysis
  - Unified timeline assembly (messages + calls + system events)
  - Async AI summary refresh scheduling (Redis debounce)

Design rules:
  - NO LLM calls in this file — all AI is async via Celery
  - All queries scoped to tenant_id
  - N+1 prevention via joinedload + batch fetch for guest_identities
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.core.cache import cache_key, get_cached, set_cached
from app.models.guest_identity import GuestIdentity, IdentityType
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.schemas.leads import (
    LeadCardSchema, LeadDetailSchema, LeadsListResponse,
    PipelineStageMetaSchema, QuoteHistorySchema, TimelineEntrySchema,
)

log = logging.getLogger(__name__)

# ── Profile completeness mapping ──────────────────────────────────────────────
# Ordered: each new signal type adds incremental completeness
_COMPLETENESS_MAP: list[tuple[str, int]] = [
    (IdentityType.INSTAGRAM_USER_ID,  30),
    (IdentityType.WHATSAPP_NUMBER,    60),
    (IdentityType.EMAIL,              70),
    (IdentityType.PHONE,              80),
    (IdentityType.BOOKING_ID,         90),
    (IdentityType.CHANNEL_THREAD_ID,  93),
    (IdentityType.OTA_GUEST_ID,       97),
    (IdentityType.CALL_RECORD_ID,    100),
]

# Source → canonical channel icon key
_SOURCE_CHANNEL_MAP: dict[str, str] = {
    "meta_ig":       "instagram",
    "wa_direct":     "whatsapp",
    "click_to_wa":   "whatsapp",
    "inbound_call":  "phone",
    "outbound_call": "phone",
    "phone":         "phone",
    "ota_airbnb":    "airbnb",
    "ota_booking":   "booking_com",
    "ota_vrbo":      "vrbo",
    "ota_mmt":       "mmt",
    "ota_goibibo":   "goibibo",
    "channel_manager": "ota",
    "web_chat":      "web",
    "website":       "web",
    "walk_in":       "walk_in",
    "referral":      "referral",
    "email":         "email",
}

# Stages grouped as "Closed" in the pipeline
_CLOSED_STAGES = {InquiryStage.LOST.value, InquiryStage.GHOSTED.value}

SUMMARY_DEBOUNCE_TTL = 1800   # 30 minutes
TIMELINE_CAP = 50


# ── Profile completeness ──────────────────────────────────────────────────────

def get_profile_completeness(
    db: Session,
    tenant_id: str,
    guest_id: str,
) -> int:
    """
    Compute profile completeness (0–100) from the guest's identity signals.
    Uses the ordered _COMPLETENESS_MAP: the highest tier reached is returned.
    """
    signal_types = {
        row.identity_type
        for row in db.query(GuestIdentity.identity_type)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .all()
    }
    completeness = 0
    for identity_type, pct in _COMPLETENESS_MAP:
        if identity_type in signal_types:
            completeness = pct
    return completeness


def _batch_completeness(
    db: Session,
    tenant_id: str,
    guest_ids: list[str],
) -> dict[str, int]:
    """Batch-fetch all GuestIdentity rows for a list of guest_ids in one query."""
    rows = (
        db.query(GuestIdentity.guest_id, GuestIdentity.identity_type)
        .filter(
            GuestIdentity.tenant_id == tenant_id,
            GuestIdentity.guest_id.in_(guest_ids),
        )
        .all()
    )
    # Group by guest_id
    signals_by_guest: dict[str, set[str]] = {}
    for guest_id, identity_type in rows:
        signals_by_guest.setdefault(guest_id, set()).add(identity_type)

    result: dict[str, int] = {}
    for guest_id in guest_ids:
        signal_types = signals_by_guest.get(guest_id, set())
        completeness = 0
        for identity_type, pct in _COMPLETENESS_MAP:
            if identity_type in signal_types:
                completeness = pct
        result[guest_id] = completeness
    return result


def _batch_signals(
    db: Session,
    tenant_id: str,
    guest_ids: list[str],
) -> dict[str, list[str]]:
    """Batch-fetch identity signal type lists per guest_id."""
    rows = (
        db.query(GuestIdentity.guest_id, GuestIdentity.identity_type)
        .filter(
            GuestIdentity.tenant_id == tenant_id,
            GuestIdentity.guest_id.in_(guest_ids),
        )
        .all()
    )
    result: dict[str, list[str]] = {gid: [] for gid in guest_ids}
    for guest_id, identity_type in rows:
        if guest_id in result:
            result[guest_id].append(identity_type)
    return result


# ── Property interest ─────────────────────────────────────────────────────────

def get_property_interest(
    db: Session,
    tenant_id: str,
    inquiry_id: str,
) -> list[str]:
    """
    Extract up to 3 distinct property names from calls linked to this inquiry.
    Reads from calls.ai_score JSON — never crashes on missing/malformed data.
    """
    from app.models.call import Call

    calls = (
        db.query(Call.ai_score)
        .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id)
        .order_by(desc(Call.created_at))
        .limit(10)
        .all()
    )

    seen: list[str] = []
    for (ai_score,) in calls:
        if not ai_score:
            continue
        try:
            data = ai_score if isinstance(ai_score, dict) else json.loads(ai_score)
            props = data.get("property_interest", [])
            for p in props:
                if p and p not in seen:
                    seen.append(p)
                if len(seen) >= 3:
                    return seen
        except Exception:
            continue
    return seen


# ── Timeline builder ──────────────────────────────────────────────────────────

def build_timeline(
    db: Session,
    tenant_id: str,
    inquiry_id: str,
    limit: int = TIMELINE_CAP,
) -> tuple[list[TimelineEntrySchema], bool]:
    """
    Build a unified timeline capped at `limit` entries.
    Returns (entries, timeline_capped).
    Sources: messages (WA+IG), calls (AI summary), system events (merge log).
    """
    from app.models.conversation import Message

    entries: list[dict[str, Any]] = []

    # ── Messages ──────────────────────────────────────────────────────────────
    # Fetch via conversations linked to this inquiry
    from app.models.conversation import Conversation
    conv_ids = [
        r.id for r in
        db.query(Conversation.id)
        .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id)
        .all()
    ]

    if conv_ids:
        messages = (
            db.query(Message)
            .filter(
                Message.tenant_id == tenant_id,
                Message.conversation_id.in_(conv_ids),
            )
            .order_by(desc(Message.created_at))
            .limit(limit + 10)   # over-fetch slightly, trim after union
            .all()
        )
        for msg in messages:
            body = msg.body or ""
            entries.append({
                "id": str(msg.id),
                "channel": msg.channel.value if hasattr(msg.channel, "value") else str(msg.channel),
                "direction": msg.direction.value if hasattr(msg.direction, "value") else str(msg.direction),
                "occurred_at": msg.created_at,
                "content_preview": body[:120],
                "is_ai_generated": bool(getattr(msg, "is_ai_generated", False)),
            })

    # ── Calls ─────────────────────────────────────────────────────────────────
    from app.models.call import Call
    calls = (
        db.query(Call)
        .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id)
        .order_by(desc(Call.created_at))
        .limit(20)
        .all()
    )
    for call in calls:
        entries.append({
            "id": str(call.id),
            "channel": "call",
            "direction": call.direction.value if hasattr(call.direction, "value") else str(call.direction),
            "occurred_at": call.created_at,
            "content_preview": (call.ai_summary or "")[:120] or "Call recorded",
            "is_ai_generated": False,
            "call_summary": call.ai_summary,
        })

    # ── System events (merge log) ─────────────────────────────────────────────
    from app.models.inquiry_360 import InquiryStageLog
    system_logs = (
        db.query(InquiryStageLog)
        .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id, changed_by="system")
        .order_by(desc(InquiryStageLog.changed_at))
        .limit(10)
        .all()
    )
    for sl in system_logs:
        if sl.to_stage == "merged":
            entries.append({
                "id": str(sl.id),
                "channel": "system",
                "direction": "system",
                "occurred_at": sl.changed_at,
                "content_preview": sl.reason or "Leads merged",
                "is_ai_generated": False,
            })

    # ── Sort, cap, return ─────────────────────────────────────────────────────
    entries.sort(key=lambda e: e["occurred_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    capped = len(entries) > limit
    entries = entries[:limit]

    timeline = [
        TimelineEntrySchema(
            id=e["id"],
            channel=e["channel"],
            direction=e["direction"],
            occurred_at=e["occurred_at"],
            content_preview=e["content_preview"],
            is_ai_generated=e.get("is_ai_generated", False),
            call_summary=e.get("call_summary"),
        )
        for e in entries
    ]
    return timeline, capped


# ── AI summary refresh ────────────────────────────────────────────────────────

def trigger_summary_refresh(
    db: Session,
    inquiry_id: str,
    tenant_id: str,
    source: str = "message",
) -> bool:
    """
    Enqueue an async AI summary generation for this inquiry.

    - source="message": debounced (30-min Redis TTL key). Skip if already queued.
    - source="call":    always immediate, skip debounce.
    - source="manual":  always immediate (POST /refresh-summary endpoint).

    Returns True if task was enqueued, False if debounced.
    """
    debounce_key = cache_key("summary_debounce", tenant_id, iid=inquiry_id)

    if source == "message":
        if get_cached(debounce_key) is not None:
            log.debug("summary_refresh_debounced", inquiry_id=inquiry_id, source=source)
            return False
        set_cached(debounce_key, "1", ttl=SUMMARY_DEBOUNCE_TTL)

    try:
        from app.workers.tasks.generate_ai_summary import generate_ai_summary
        generate_ai_summary.delay(inquiry_id=inquiry_id, tenant_id=tenant_id)
        log.info("summary_refresh_queued", inquiry_id=inquiry_id, source=source)
        return True
    except Exception as exc:
        log.warning("summary_refresh_enqueue_failed", inquiry_id=inquiry_id, error=str(exc))
        return False


# ── Pipeline query ────────────────────────────────────────────────────────────

def _build_lead_card(
    inquiry: Inquiry,
    completeness: int,
    signals: list[str],
    property_interest: list[str],
) -> LeadCardSchema:
    """Build a LeadCardSchema from an Inquiry ORM object and precomputed fields."""
    guest = inquiry.guest
    assigned = inquiry.assigned_user

    display_name = "Unknown Guest"
    if guest and guest.name:
        display_name = guest.name

    source_val = inquiry.source.value if inquiry.source else None
    primary_channel = _SOURCE_CHANNEL_MAP.get(source_val or "", None)

    stage_val = inquiry.stage.value if inquiry.stage else "new"
    if stage_val in _CLOSED_STAGES:
        stage_val = "closed"

    return LeadCardSchema(
        inquiry_id=str(inquiry.id),
        guest_id=str(inquiry.guest_id),
        display_name=display_name,
        profile_completeness_pct=completeness,
        identity_signals=signals,
        source=source_val,
        primary_channel=primary_channel,
        inquiry_stage=stage_val,
        sla_breached=bool(inquiry.sla_breached),
        occasion=inquiry.occasion,
        group_type=inquiry.intent_tag,
        check_in=inquiry.check_in,
        check_out=inquiry.check_out,
        adults=inquiry.adults,
        children=inquiry.children,
        budget_estimate=float(inquiry.budget) if inquiry.budget else None,
        budget_currency=inquiry.currency or "INR",
        quoted_amount=float(inquiry.quoted_amount) if inquiry.quoted_amount else None,
        quoted_at=inquiry.quoted_at,
        property_interest=property_interest,
        ai_summary=inquiry.ai_summary,
        ai_next_action=inquiry.ai_next_action,
        assigned_agent_name=assigned.name if assigned else None,
        assigned_agent_id=str(assigned.id) if assigned else None,
        last_touch_at=inquiry.updated_at,
        created_at=inquiry.created_at,
    )


def get_leads_pipeline(
    db: Session,
    tenant_id: str,
    stage: Optional[str] = None,
    property_id: Optional[str] = None,
    assigned_to: Optional[str] = None,
    source: Optional[str] = None,
    occasion: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    checkin_date_from: Optional[str] = None,
    checkin_date_to: Optional[str] = None,
    booked_date_from: Optional[str] = None,
    booked_date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
) -> LeadsListResponse:
    """
    Paginated pipeline query. One row per inquiry.
    Uses joinedload to avoid N+1 on guest + assigned_user.
    Batch-fetches guest_identities for all guest_ids in the page.

    date_from/date_to filter enquiry date (inquiries.created_at).
    checkin_date_from/to filter inquiries.check_in -- stored as an ISO
    'YYYY-MM-DD' string; string BETWEEN is correct here since same-format
    ISO dates sort lexicographically identically to chronological order.
    booked_date_from/to filter on the date the inquiry entered whichever
    pipeline_stages row has is_closed_won=true for this tenant (restructure
    plan §3.1 -- there's no stored Hostaway reservation date in HAIP yet).
    """
    q = (
        db.query(Inquiry)
        .options(
            joinedload(Inquiry.guest),
            joinedload(Inquiry.assigned_user),
        )
        .filter(Inquiry.tenant_id == tenant_id)
    )

    # Filters
    if stage:
        # "closed" is a UI alias for lost + ghosted
        if stage == "closed":
            q = q.filter(Inquiry.stage.in_([InquiryStage.LOST, InquiryStage.GHOSTED]))
        else:
            q = q.filter(Inquiry.stage == stage)
    if property_id:
        q = q.filter(Inquiry.property_id == property_id)
    if assigned_to:
        q = q.filter(Inquiry.assigned_to == assigned_to)
    if source:
        q = q.filter(Inquiry.source == source)
    if occasion:
        q = q.filter(Inquiry.occasion.ilike(f"%{occasion}%"))
    if date_from:
        q = q.filter(Inquiry.created_at >= date_from)
    if date_to:
        q = q.filter(Inquiry.created_at <= date_to)
    if checkin_date_from:
        q = q.filter(Inquiry.check_in >= checkin_date_from)
    if checkin_date_to:
        q = q.filter(Inquiry.check_in <= checkin_date_to)
    if booked_date_from or booked_date_to:
        q = q.filter(Inquiry.id.in_(
            _booked_inquiry_ids(db, tenant_id, booked_date_from, booked_date_to)
        ))

    total = q.count()

    inquiries = (
        q.order_by(desc(Inquiry.updated_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    if not inquiries:
        return LeadsListResponse(total=total, page=page, page_size=page_size)

    # Batch-fetch identity data for all guests in this page (prevents N+1)
    guest_ids = [inq.guest_id for inq in inquiries]
    completeness_map = _batch_completeness(db, tenant_id, guest_ids)
    signals_map = _batch_signals(db, tenant_id, guest_ids)

    # Batch-fetch property interest per inquiry (calls.ai_score)
    prop_interest_map: dict[str, list[str]] = {
        inq.id: get_property_interest(db, tenant_id, inq.id)
        for inq in inquiries
    }

    leads = [
        _build_lead_card(
            inq,
            completeness=completeness_map.get(inq.guest_id, 0),
            signals=signals_map.get(inq.guest_id, []),
            property_interest=prop_interest_map.get(inq.id, []),
        )
        for inq in inquiries
    ]

    # Stage summary (count + potential revenue across ALL filtered leads, not just this page)
    stage_meta = _build_stage_summary(db, tenant_id, stage, property_id, assigned_to, source)

    return LeadsListResponse(
        total=total,
        page=page,
        page_size=page_size,
        stages=stage_meta,
        leads=leads,
    )


def _booked_inquiry_ids(
    db: Session, tenant_id: str, date_from: Optional[str], date_to: Optional[str],
) -> list[str]:
    """Inquiry IDs that entered a closed-won pipeline stage within the given
    range, per the earliest matching InquiryStageLog row (an inquiry can
    only enter closed-won once in practice, but earliest is used defensively
    in case of a stage reversal + re-close)."""
    from app.models.inquiry_360 import InquiryStageLog
    from app.models.pipeline_stage import PipelineStage

    won_keys = [
        row.key for row in
        db.query(PipelineStage.key).filter_by(tenant_id=tenant_id, is_closed_won=True).all()
    ]
    if not won_keys:
        return []

    q = (
        db.query(InquiryStageLog.inquiry_id)
        .filter(
            InquiryStageLog.tenant_id == tenant_id,
            InquiryStageLog.to_stage.in_(won_keys),
        )
    )
    if date_from:
        q = q.filter(InquiryStageLog.changed_at >= date_from)
    if date_to:
        q = q.filter(InquiryStageLog.changed_at <= date_to)
    return [r.inquiry_id for r in q.all()]


def _build_stage_summary(
    db: Session,
    tenant_id: str,
    stage_filter: Optional[str],
    property_id: Optional[str],
    assigned_to: Optional[str],
    source: Optional[str],
) -> dict[str, PipelineStageMetaSchema]:
    """Compute count + potential_revenue per stage across all matching inquiries."""
    from sqlalchemy import func, case
    from app.models.inquiry import Inquiry as Inq

    q = db.query(
        Inq.stage,
        func.count(Inq.id).label("cnt"),
        func.coalesce(func.sum(
            case(
                (Inq.quoted_amount.isnot(None), Inq.quoted_amount),
                else_=func.coalesce(Inq.budget, 0),
            )
        ), 0).label("revenue"),
    ).filter(Inq.tenant_id == tenant_id)

    if property_id:
        q = q.filter(Inq.property_id == property_id)
    if assigned_to:
        q = q.filter(Inq.assigned_to == assigned_to)
    if source:
        q = q.filter(Inq.source == source)

    rows = q.group_by(Inq.stage).all()

    result: dict[str, PipelineStageMetaSchema] = {}
    for row in rows:
        s = row.stage.value if hasattr(row.stage, "value") else str(row.stage)
        if s in _CLOSED_STAGES:
            s = "closed"
        if s not in result:
            result[s] = PipelineStageMetaSchema()
        result[s].count += row.cnt
        result[s].potential_revenue += float(row.revenue)

    return result


# ── Detail query ──────────────────────────────────────────────────────────────

def get_lead_detail(
    db: Session,
    tenant_id: str,
    inquiry_id: str,
) -> Optional[LeadDetailSchema]:
    """
    Return full lead detail including timeline and quote history.
    Returns None if inquiry not found or belongs to another tenant.
    """
    inquiry = (
        db.query(Inquiry)
        .options(
            joinedload(Inquiry.guest),
            joinedload(Inquiry.assigned_user),
        )
        .filter_by(id=inquiry_id, tenant_id=tenant_id)
        .first()
    )
    if not inquiry:
        return None

    completeness = get_profile_completeness(db, tenant_id, inquiry.guest_id)
    signals = [
        row.identity_type
        for row in db.query(GuestIdentity.identity_type)
        .filter_by(tenant_id=tenant_id, guest_id=inquiry.guest_id)
        .all()
    ]
    property_interest = get_property_interest(db, tenant_id, inquiry_id)
    timeline, capped = build_timeline(db, tenant_id, inquiry_id)

    # Quote history
    from app.models.inquiry_360 import InquiryQuote
    from datetime import date as date_cls

    quotes_raw = (
        db.query(InquiryQuote)
        .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id)
        .order_by(desc(InquiryQuote.created_at))
        .all()
    )
    today = datetime.now(timezone.utc).date()
    quote_history = [
        QuoteHistorySchema(
            id=str(q.id),
            amount=float(q.amount),
            currency=q.currency,
            created_at=q.created_at,
            is_active=q.is_active,
            age_days=(today - q.created_at.date()).days if q.created_at else None,
        )
        for q in quotes_raw
    ]

    card = _build_lead_card(inquiry, completeness, signals, property_interest)

    from app.services.lead_field_service import get_field_values_for_inquiry
    try:
        custom_field_values = get_field_values_for_inquiry(db, tenant_id, inquiry, detail_only=True)
    except Exception as exc:
        # Field registry is additive UI enrichment -- never break lead detail
        # over it (e.g. a tenant with zero rows before migration backfill).
        log.warning("lead_field_values_failed", inquiry_id=inquiry_id, error=str(exc))
        custom_field_values = []

    return LeadDetailSchema(
        **card.model_dump(),
        timeline=timeline,
        timeline_capped=capped,
        timeline_total_available=len(timeline),
        quote_history=quote_history,
        custom_field_values=custom_field_values,
    )
