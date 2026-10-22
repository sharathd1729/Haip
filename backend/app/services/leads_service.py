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
import structlog
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import desc, false as sa_false, or_
from sqlalchemy.orm import Session, joinedload

from app.core.cache import cache_key, get_cached, set_cached
from app.models.guest_identity import GuestIdentity, IdentityType
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.services import lead_list_extras
from app.schemas.leads import (
    LeadCardSchema, LeadDetailSchema, LeadsListResponse, NeedsActionBucket,
    NeedsActionKpis, NeedsActionResponse, PendingDraftSchema,
    PipelineStageMetaSchema, QuoteHistorySchema, TimelineEntrySchema,
)

# structlog, not stdlib logging: the log calls in this module pass structured
# kwargs (inquiry_id=..., source=...). stdlib's Logger.info() rejects those with
# TypeError — but only once the level is enabled, so this was silent at WARNING
# and broke trigger_summary_refresh() at INFO, where the success log raised
# inside the try block and the except handler then raised again on its own
# kwargs, surfacing a successful enqueue as a failure.
log = structlog.get_logger()

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
    "organic_call":  "phone",
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

SUMMARY_DEBOUNCE_TTL = 600    # 10 minutes: a new message is reflected in the analysis within this window (was 30)
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


# ── Response time (computed on read, never stored) ───────────────────────────
# The stored Inquiry.first_response_at / sla_breached columns are dead — no
# code path writes them. Same computed-on-read pattern as
# profile_completeness_pct; see LeadCardSchema for the field contract.

def _batch_response_time(
    db: Session,
    tenant_id: str,
    inquiry_ids: list[str],
    now: Optional[datetime] = None,
) -> dict[str, tuple[int, str]]:
    """Per-inquiry response time across all its conversations, in two batch
    queries (no N+1): (1) latest inbound message per conversation, (2) the
    earliest outbound after that inbound. A conversation whose last inbound
    has no later outbound is "waiting" (seconds = wait so far); otherwise
    "responded" (seconds = inbound→reply gap). Per inquiry, any waiting
    conversation outranks responded ones, and the longest wait wins.

    Returns {inquiry_id: (seconds, status)}; inquiries with no inbound
    messages are absent from the result."""
    from sqlalchemy import func
    from app.models.conversation import Conversation, Message, MessageDirection

    if not inquiry_ids:
        return {}
    now = now or datetime.now(timezone.utc)

    last_inbound_sq = (
        db.query(
            Message.conversation_id.label("conv_id"),
            func.max(Message.created_at).label("last_in_at"),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.INBOUND,
            Conversation.inquiry_id.in_(inquiry_ids),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    # (conversation_id, inquiry_id, last inbound time) for every conversation
    # that has at least one inbound message
    inbound_rows = (
        db.query(Conversation.id, Conversation.inquiry_id, last_inbound_sq.c.last_in_at)
        .join(last_inbound_sq, last_inbound_sq.c.conv_id == Conversation.id)
        .all()
    )
    if not inbound_rows:
        return {}

    # Earliest outbound strictly after each conversation's last inbound
    first_reply_rows = (
        db.query(
            Message.conversation_id,
            func.min(Message.created_at).label("first_out_at"),
        )
        .join(last_inbound_sq, last_inbound_sq.c.conv_id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at > last_inbound_sq.c.last_in_at,
            # Only messages that actually reached the guest count as a reply.
            # A pending (was_approved=None) or rejected (False) AI draft is
            # also an OUTBOUND row -- counting it marked guests "responded"
            # the moment a draft was written, so a lead whose only answer
            # was an unsent draft never showed as waiting. Auto-sent and
            # approved AI replies carry was_approved=True.
            or_(Message.is_ai_generated.isnot(True), Message.was_approved.is_(True)),
        )
        .group_by(Message.conversation_id)
        .all()
    )
    reply_at_by_conv = {conv_id: t for conv_id, t in first_reply_rows}

    def _aware(dt: datetime) -> datetime:
        # SQLite (tests) returns naive datetimes even for timezone=True columns
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    result: dict[str, tuple[int, str]] = {}
    for conv_id, inquiry_id, last_in_at in inbound_rows:
        last_in = _aware(last_in_at)
        reply_at = reply_at_by_conv.get(conv_id)
        if reply_at is None:
            seconds = max(0, int((now - last_in).total_seconds()))
            status = "waiting"
        else:
            seconds = max(0, int((_aware(reply_at) - last_in).total_seconds()))
            status = "responded"

        prev = result.get(inquiry_id)
        if prev is None:
            result[inquiry_id] = (seconds, status)
            continue
        prev_seconds, prev_status = prev
        # waiting outranks responded; within the same status, longest wins
        if (status == "waiting" and prev_status != "waiting") or (
            status == prev_status and seconds > prev_seconds
        ):
            result[inquiry_id] = (seconds, status)
    return result


# ── Pending AI drafts (M5+ WS3) ───────────────────────────────────────────────

def _batch_pending_drafts(
    db: Session,
    tenant_id: str,
    inquiry_ids: list[str],
) -> dict[str, PendingDraftSchema]:
    """Most recent pending AI-drafted reply per inquiry, in one query (no
    N+1) — same "pending draft" representation concierge_draft already
    writes (is_ai_generated=True, was_approved=None). Returns
    {inquiry_id: PendingDraftSchema}; inquiries with no pending draft are
    absent from the result."""
    from app.models.conversation import Conversation, Message, MessageDirection

    if not inquiry_ids:
        return {}

    rows = (
        db.query(Message.id, Message.conversation_id, Message.body, Conversation.inquiry_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.is_ai_generated.is_(True),
            Message.was_approved.is_(None),
            Message.direction == MessageDirection.OUTBOUND,
            Conversation.inquiry_id.in_(inquiry_ids),
        )
        .order_by(Message.created_at.desc())
        .all()
    )

    result: dict[str, PendingDraftSchema] = {}
    for msg_id, conv_id, body, inquiry_id in rows:
        if inquiry_id in result:
            continue  # already have the most recent (rows are newest-first)
        result[inquiry_id] = PendingDraftSchema(
            message_id=msg_id,
            conversation_id=conv_id,
            preview=(body or "")[:140],
        )
    return result


def _batch_needs_agent_followup(
    db: Session,
    tenant_id: str,
    inquiry_ids: list[str],
) -> dict[str, str]:
    """Most recent auto-sent reply per inquiry that the AI itself flagged as
    needing a human's personal follow-up (soft escalation -- the draft was
    correct and safe to send, but the model judged the outcome needs a
    person, e.g. a complex custom quote or a frustrated guest). One query,
    no N+1, same shape as _batch_pending_drafts above.

    concierge_draft.py's auto-send/hard_block plan: hard-block guards
    (hallucination, price leak, escalation keyword, rate limit) still hold
    the draft for manual approval -- those never reach here, since
    sent_autonomously stays False for them. Only a soft self-flagged send
    (sent_autonomously=True AND a reason was persisted) lands here.
    Returns {inquiry_id: reason_text}; inquiries with no such send are
    absent from the result."""
    from app.models.conversation import Conversation, Message, MessageDirection

    if not inquiry_ids:
        return {}

    rows = (
        db.query(Message.created_at, Message.ai_needs_human_reason, Conversation.inquiry_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.sent_autonomously.is_(True),
            Message.ai_needs_human_reason.isnot(None),
            Conversation.inquiry_id.in_(inquiry_ids),
        )
        .order_by(Message.created_at.desc())
        .all()
    )

    result: dict[str, str] = {}
    for _created_at, reason, inquiry_id in rows:
        if inquiry_id in result:
            continue  # already have the most recent (rows are newest-first)
        result[inquiry_id] = reason
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


def _batch_property_interest(
    db: Session,
    tenant_id: str,
    inquiry_ids: list[str],
) -> dict[str, list[str]]:
    """Same extraction as get_property_interest(), batched across many
    inquiries in one query instead of one query per inquiry.

    get_leads_pipeline() used to call get_property_interest() inside a
    per-inquiry dict comprehension -- looked like a batch step (it's built
    into the same dict-comprehension block as the real _batch_* helpers
    below) but was actually N individual queries. Against Ratha's real data
    (683 inquiries) that alone made page_size=25 take ~2s and page_size=1000
    take ~36s, both wildly outside CLAUDE.md's <200ms budget for this
    endpoint -- confirmed by direct timing before this fix, not assumed.
    """
    from app.models.call import Call

    if not inquiry_ids:
        return {}

    rows = (
        db.query(Call.inquiry_id, Call.ai_score)
        .filter(Call.tenant_id == tenant_id, Call.inquiry_id.in_(inquiry_ids))
        .order_by(Call.inquiry_id, desc(Call.created_at))
        .all()
    )

    result: dict[str, list[str]] = {}
    examined: dict[str, int] = {}
    for inquiry_id, ai_score in rows:
        seen = result.setdefault(inquiry_id, [])
        if len(seen) >= 3:
            continue
        # Same "look at up to 10 most recent calls" cap as the single-inquiry
        # version's .limit(10), reimplemented per-group since a single query
        # can't apply a per-group LIMIT portably.
        n = examined.get(inquiry_id, 0)
        if n >= 10:
            continue
        examined[inquiry_id] = n + 1
        if not ai_score:
            continue
        try:
            data = ai_score if isinstance(ai_score, dict) else json.loads(ai_score)
        except Exception:
            continue
        for p in data.get("property_interest", []):
            if p and p not in seen:
                seen.append(p)
            if len(seen) >= 3:
                break
    return result


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
                "full_content": body or None,
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
            "call_duration_seconds": call.duration_seconds,
            "call_qa_score": float(call.ai_score) if call.ai_score is not None else None,
            "call_has_transcript": bool(call.transcript_json),
            "call_next_action": call.ai_next_action,
            "call_disposition": (call.human_disposition or call.ai_disposition).value
                if (call.human_disposition or call.ai_disposition) else None,
            "call_occasion": call.occasion,
            "call_budget_signal": call.budget_signal,
            "call_decision_stage": call.decision_stage,
            "call_competitor_mentioned": call.competitor_mentioned,
            "call_conversion_probability": call.conversion_probability,
            "call_lost_reason": call.lost_reason,
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

    # ── Quotes (rate calculator and quote builder) ────────────────────────────
    from app.services.lead_quote_view import timeline_entries
    entries.extend(timeline_entries(db, tenant_id, inquiry_id))

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
            full_content=e.get("full_content"),
            is_ai_generated=e.get("is_ai_generated", False),
            call_summary=e.get("call_summary"),
            call_duration_seconds=e.get("call_duration_seconds"),
            call_qa_score=e.get("call_qa_score"),
            call_has_transcript=e.get("call_has_transcript", False),
            call_next_action=e.get("call_next_action"),
            call_disposition=e.get("call_disposition"),
            call_occasion=e.get("call_occasion"),
            call_budget_signal=e.get("call_budget_signal"),
            call_decision_stage=e.get("call_decision_stage"),
            call_competitor_mentioned=e.get("call_competitor_mentioned"),
            call_conversion_probability=e.get("call_conversion_probability"),
            call_lost_reason=e.get("call_lost_reason"),
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

    - source="message": debounced (30-min Redis TTL key). A message that
      lands while already debounced schedules one trailing catch-up run at
      the end of the window instead of being silently dropped -- otherwise
      a guest who sends their travel dates/guest count in a second message
      right after their first never gets that captured until some unrelated
      later trigger (a call, a manual refresh) happens to fire. The task
      always rebuilds context fresh from the DB at execution time, so a
      delayed run correctly reflects whatever arrived in the meantime.
    - source="call":    always immediate, skip debounce.
    - source="manual":  always immediate (POST /refresh-summary endpoint).

    Returns True if task was enqueued (immediately or as a scheduled
    catch-up), False if this call was fully absorbed by an already-scheduled
    catch-up.
    """
    debounce_key = cache_key("summary_debounce", tenant_id, iid=inquiry_id)

    if source == "message":
        if get_cached(debounce_key) is not None:
            followup_key = cache_key("summary_followup", tenant_id, iid=inquiry_id)
            if get_cached(followup_key) is not None:
                log.debug("summary_refresh_debounced", inquiry_id=inquiry_id, source=source)
                return False
            set_cached(followup_key, "1", ttl=SUMMARY_DEBOUNCE_TTL)
            try:
                from app.workers.tasks.generate_ai_summary import generate_ai_summary
                generate_ai_summary.apply_async(
                    kwargs={"inquiry_id": inquiry_id, "tenant_id": tenant_id},
                    countdown=SUMMARY_DEBOUNCE_TTL,
                )
                log.info("summary_refresh_followup_scheduled", inquiry_id=inquiry_id, source=source)
                return True
            except Exception as exc:
                log.warning("summary_refresh_followup_enqueue_failed", inquiry_id=inquiry_id, error=str(exc))
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
    response_time: Optional[tuple[int, str]] = None,
    pending_draft: Optional[PendingDraftSchema] = None,
    needs_agent_followup_reason: Optional[str] = None,
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
        stage_key=inquiry.pipeline_stage.key if inquiry.pipeline_stage else None,
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
        ai_analysis=inquiry.ai_analysis,
        assigned_agent_name=assigned.name if assigned else None,
        assigned_agent_id=str(assigned.id) if assigned else None,
        assigned_agent_avatar_url=assigned.avatar_url if assigned else None,
        last_touch_at=inquiry.updated_at,
        created_at=inquiry.created_at,
        response_time_seconds=response_time[0] if response_time else None,
        response_time_status=response_time[1] if response_time else None,
        pending_draft=pending_draft,
        needs_agent_followup=needs_agent_followup_reason is not None,
        needs_agent_followup_reason=needs_agent_followup_reason,
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
    scope_user_id: Optional[str] = None,
    autopilot: Optional[str] = None,
    lead_type: Optional[str] = None, came_from: Optional[str] = None,   # lead_list_extras (CRM reporting, 22 Oct 2026)
) -> LeadsListResponse:
    """
    Paginated pipeline query. One row per inquiry.
    Uses joinedload to avoid N+1 on guest + assigned_user.
    Batch-fetches guest_identities for all guest_ids in the page.

    `scope_user_id` is the tenant-wide-visibility guard (leads.py forces this
    to the caller's own id for every role except owner/manager) -- distinct
    from `assigned_to`, which is a caller-chosen filter. A non-owner sees
    their own leads plus unclaimed ones, never a peer's; owners/managers pass
    None here regardless of what `assigned_to` narrows the view to.

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
            joinedload(Inquiry.pipeline_stage),
        )
        .filter(Inquiry.tenant_id == tenant_id)
        # Leads360 restructure Phase 4: unqualified inquiries are hidden
        # entirely from the pipeline (per your call) -- they still exist
        # as rows (fail-loudly, nothing is silently dropped), just never
        # surface here. Default "qualified" for every existing creation
        # path means this is a no-op until a tenant configures
        # required_for_lead fields.
        .filter(Inquiry.qualification_status != "unqualified")
    )

    # Filters
    if stage:
        # "closed" is a legacy UI alias for lost + ghosted, predating
        # tenant-owned pipeline_stages -- kept for any caller still sending
        # it, though the new taxonomy already exposes Lost/Sold as their
        # own distinct columns and has no need for this grouping.
        if stage == "closed":
            q = q.filter(Inquiry.stage.in_([InquiryStage.LOST, InquiryStage.GHOSTED]))
        else:
            # Board columns are keyed by pipeline_stages.key (tenant-owned,
            # arbitrary), not the legacy Inquiry.stage enum -- filter via
            # stage_id. Comparing `stage` directly against the enum column
            # only ever worked by coincidence when a tenant's stage keys
            # happened to equal the old fixed enum values (new/responding/
            # etc.); any tenant-custom or new-taxonomy key (general_enquiry,
            # active, ...) silently matched zero rows under that comparison.
            stage_row = (
                db.query(PipelineStage.id)
                .filter_by(tenant_id=tenant_id, key=stage)
                .first()
            )
            if stage_row:
                q = q.filter(Inquiry.stage_id == stage_row[0])
            else:
                try:
                    q = q.filter(Inquiry.stage == InquiryStage(stage))
                except ValueError:
                    q = q.filter(sa_false())
    if property_id:
        q = q.filter(Inquiry.property_id == property_id)
    if scope_user_id:
        q = q.filter(or_(Inquiry.assigned_to == scope_user_id, Inquiry.assigned_to.is_(None)))
    if assigned_to == UNASSIGNED:
        q = q.filter(Inquiry.assigned_to.is_(None))
    elif assigned_to:
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
    if autopilot == "moved":
        from app.services.lead_autopilot_view import moved_filter
        q = q.filter(moved_filter(db, tenant_id))
    q = lead_list_extras.apply_filters(db, q, tenant_id, lead_type, came_from)

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
    prop_interest_map = _batch_property_interest(db, tenant_id, [inq.id for inq in inquiries])

    response_time_map = _batch_response_time(db, tenant_id, [inq.id for inq in inquiries])
    pending_draft_map = _batch_pending_drafts(db, tenant_id, [inq.id for inq in inquiries])
    needs_followup_map = _batch_needs_agent_followup(db, tenant_id, [inq.id for inq in inquiries])

    leads = [
        _build_lead_card(
            inq,
            completeness=completeness_map.get(inq.guest_id, 0),
            signals=signals_map.get(inq.guest_id, []),
            property_interest=prop_interest_map.get(inq.id, []),
            response_time=response_time_map.get(inq.id),
            pending_draft=pending_draft_map.get(inq.id),
            needs_agent_followup_reason=needs_followup_map.get(inq.id),
        )
        for inq in inquiries
    ]
    try:
        from app.services.lead_autopilot_view import batch_moves
        moves = batch_moves(db, tenant_id, [inq.id for inq in inquiries])
        for card in leads:
            card.autopilot_move = moves.get(card.inquiry_id)
    except Exception as exc:   # a badge must never break the list
        log.warning("lead_autopilot_badges_failed", tenant_id=tenant_id, error=str(exc)[:200])
    try:
        from app.services.lead_quote_view import latest_for
        latest = latest_for(db, tenant_id, [inq.id for inq in inquiries])
        for card in leads:
            card.latest_quote = latest.get(card.inquiry_id)
    except Exception as exc:   # the quote line must never break the list
        log.warning("lead_latest_quote_failed", tenant_id=tenant_id, error=str(exc)[:200])
    _decorate_extras(db, tenant_id, leads, inquiries)

    # Stage summary (count + potential revenue across ALL filtered leads, not just this page)
    stage_meta = _build_stage_summary(
        db, tenant_id, stage, property_id, assigned_to, source, scope_user_id,
        occasion=occasion, date_from=date_from, date_to=date_to,
        checkin_date_from=checkin_date_from, checkin_date_to=checkin_date_to,
        booked_date_from=booked_date_from, booked_date_to=booked_date_to, lead_type=lead_type, came_from=came_from,
    )

    return LeadsListResponse(
        total=total,
        page=page,
        page_size=page_size,
        stages=stage_meta,
        leads=leads,
    )


def _decorate_extras(db: Session, tenant_id: str, cards: list, inquiries: list) -> None:
    try:   # lead type, paid / organic, the human review -- never break the list over a label
        lead_list_extras.decorate(db, tenant_id, cards, inquiries)
    except Exception as exc:
        log.warning("lead_list_extras_failed", tenant_id=tenant_id, error=str(exc)[:200])


# `assigned_to=unassigned` on the leads list means "nobody owns it yet".
UNASSIGNED = "unassigned"


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
    scope_user_id: Optional[str] = None,
    occasion: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    checkin_date_from: Optional[str] = None,
    checkin_date_to: Optional[str] = None,
    booked_date_from: Optional[str] = None,
    booked_date_to: Optional[str] = None,
    lead_type: Optional[str] = None, came_from: Optional[str] = None,
) -> dict[str, PipelineStageMetaSchema]:
    """Compute count + potential_revenue per stage across all matching inquiries.

    Groups on the tenant's pipeline_stages.key (via Inq.stage_id), not the
    legacy Inq.stage enum -- the enum grouping only ever matched by
    coincidence for tenants whose stage keys equalled the old fixed enum
    values (see get_leads_pipeline's `stage` filter fix, same bug class).
    Inquiries with no stage_id yet (pre-restructure rows never synced) are
    excluded -- an unmapped key isn't a real board column."""
    from sqlalchemy import func, case
    from app.models.inquiry import Inquiry as Inq
    from app.models.pipeline_stage import PipelineStage as PS

    q = db.query(
        PS.key,
        func.count(Inq.id).label("cnt"),
        func.coalesce(func.sum(
            case(
                (Inq.quoted_amount.isnot(None), Inq.quoted_amount),
                else_=func.coalesce(Inq.budget, 0),
            )
        ), 0).label("revenue"),
    ).join(PS, PS.id == Inq.stage_id).filter(
        Inq.tenant_id == tenant_id, PS.tenant_id == tenant_id,
        Inq.qualification_status != "unqualified",
    )

    if property_id:
        q = q.filter(Inq.property_id == property_id)
    if scope_user_id:
        q = q.filter(or_(Inq.assigned_to == scope_user_id, Inq.assigned_to.is_(None)))
    if assigned_to == UNASSIGNED:
        q = q.filter(Inq.assigned_to.is_(None))
    elif assigned_to:
        q = q.filter(Inq.assigned_to == assigned_to)
    if source:
        q = q.filter(Inq.source == source)
    # The chips must count exactly what the list below them shows: every filter the list applies is applied here too
    # (they used to be ignored, so with a date range set a stage chip said 40 while the column held 12).
    if occasion:
        q = q.filter(Inq.occasion.ilike(f"%{occasion}%"))
    if date_from:
        q = q.filter(Inq.created_at >= date_from)
    if date_to:
        q = q.filter(Inq.created_at <= date_to)
    if checkin_date_from:
        q = q.filter(Inq.check_in >= checkin_date_from)
    if checkin_date_to:
        q = q.filter(Inq.check_in <= checkin_date_to)
    if booked_date_from or booked_date_to:
        q = q.filter(Inq.id.in_(_booked_inquiry_ids(db, tenant_id, booked_date_from, booked_date_to)))
    q = lead_list_extras.apply_filters(db, q, tenant_id, lead_type, came_from)

    rows = q.group_by(PS.key).all()

    result: dict[str, PipelineStageMetaSchema] = {}
    for row in rows:
        s = row.key
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
    scope_user_id: Optional[str] = None,
) -> Optional[LeadDetailSchema]:
    """
    Return full lead detail including timeline and quote history.
    Returns None if inquiry not found or belongs to another tenant.

    `scope_user_id` mirrors get_leads_pipeline's guard -- without it, a
    non-owner/manager agent who can no longer see a peer's lead on the
    board could still open it directly by guessing/reusing its inquiry_id
    in the URL. None here (owner/manager) skips the check entirely.
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
    if scope_user_id and inquiry.assigned_to and inquiry.assigned_to != scope_user_id:
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
    from app.services.quote_journey import link_out
    from app.services.quote_send_service import latest_links
    quote_links = {k: link_out(v) for k, v in latest_links(db, tenant_id, [q.id for q in quotes_raw]).items()}
    quote_history = [
        QuoteHistorySchema(
            id=str(q.id),
            amount=float(q.amount),
            currency=q.currency,
            created_at=q.created_at,
            is_active=q.is_active,
            age_days=(today - q.created_at.date()).days if q.created_at else None,
            status=q.status,
            option_rank=q.option_rank or 1,
            payment_link_status=(quote_links.get(q.id) or {}).get("status"),
            payment_link_url=(quote_links.get(q.id) or {}).get("short_url"),
            booking_id=(quote_links.get(q.id) or {}).get("booking_id"),
            shared_via=q.shared_via,
            valid_until=q.valid_until,
            label=(q.snapshot or {}).get("package_name") or q.package_key,
        )
        for q in quotes_raw
    ]

    response_time = _batch_response_time(db, tenant_id, [inquiry_id]).get(inquiry_id)
    pending_draft = _batch_pending_drafts(db, tenant_id, [inquiry_id]).get(inquiry_id)
    needs_followup_reason = _batch_needs_agent_followup(db, tenant_id, [inquiry_id]).get(inquiry_id)
    card = _build_lead_card(
        inquiry, completeness, signals, property_interest, response_time, pending_draft,
        needs_agent_followup_reason=needs_followup_reason,
    )
    from app.services.lead_quote_view import card_out
    newest = next((q for q in quotes_raw if q.status in ("issued", "pending_approval", "accepted") and (q.option_rank or 1) == 1), None)
    card.latest_quote = card_out(newest) if newest else None
    _decorate_extras(db, tenant_id, [card], [inquiry])

    from app.services.lead_field_service import get_field_values_for_inquiry
    try:
        custom_field_values = get_field_values_for_inquiry(db, tenant_id, inquiry, detail_only=True)
    except Exception as exc:
        # Field registry is additive UI enrichment -- never break lead detail
        # over it (e.g. a tenant with zero rows before migration backfill).
        log.warning("lead_field_values_failed", inquiry_id=inquiry_id, error=str(exc))
        custom_field_values = []

    from app.services.lead_recommendation_service import get_lead_recommendation
    try:
        recommendation = get_lead_recommendation(db, tenant_id, inquiry)
    except Exception as exc:
        # Advisory only -- never break lead detail over a suggestion.
        log.warning("lead_recommendation_failed", inquiry_id=inquiry_id, error=str(exc))
        recommendation = None
    recommended_actions = [recommendation] if recommendation else []

    # Lead autopilot: what it did (with Undo) and what it suggests. Its open suggestion replaces the older call-only
    # recommendation above (same RecommendedAction shape, same audited Apply path); none at all while the lead is pinned.
    autopilot_block = None
    try:
        from app.services import lead_autopilot_view
        autopilot_block = lead_autopilot_view.lead_block(db, tenant_id, inquiry)
        suggested = lead_autopilot_view.as_recommended_action(autopilot_block)
        if autopilot_block["pinned"] or autopilot_block["mode"] == "off":
            recommended_actions = []
        elif suggested:
            recommended_actions = [suggested]
    except Exception as exc:
        log.warning("lead_autopilot_block_failed", inquiry_id=inquiry_id, error=str(exc)[:200])

    return LeadDetailSchema(
        **card.model_dump(),
        timeline=timeline,
        timeline_capped=capped,
        timeline_total_available=len(timeline),
        quote_history=quote_history,
        custom_field_values=custom_field_values,
        recommended_actions=recommended_actions,
        autopilot=autopilot_block,
    )


# ── Reporting aggregations ──────────────────────────────────────────────────

def get_source_breakdown(
    db: Session,
    tenant_id: str,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> list[dict]:
    """Lead count per inquiries.source, with conversion rate to a closed-won
    pipeline stage. Same PipelineStage join style as _build_stage_summary."""
    from sqlalchemy import func, case

    q = (
        db.query(
            Inquiry.source,
            func.count(Inquiry.id).label("total"),
            func.coalesce(func.sum(case((PipelineStage.is_closed_won.is_(True), 1), else_=0)), 0).label("won"),
        )
        .outerjoin(PipelineStage, PipelineStage.id == Inquiry.stage_id)
        .filter(Inquiry.tenant_id == tenant_id)
    )
    if date_from:
        q = q.filter(Inquiry.created_at >= date_from)
    if date_to:
        q = q.filter(Inquiry.created_at <= date_to)

    rows = q.group_by(Inquiry.source).all()
    return [
        {
            "source": row.source.value if row.source else "UNKNOWN",
            "total_leads": row.total,
            "converted": row.won,
            "conversion_rate": round(row.won / row.total, 4) if row.total else 0.0,
        }
        for row in rows
    ]


def get_daily_lead_funnel(
    db: Session,
    tenant_id: str,
    date_from: datetime,
    date_to: datetime,
) -> list[dict]:
    """Per-day lead counts split by pipeline_stages.category ("valid" is the
    only category that counts as a real lead per the category column's own
    docstring in pipeline_stage.py) plus closed-won conversions.

    Inquiries whose stage_id hasn't been backfilled to a PipelineStage yet
    fall into neither "valid" nor "invalid" -- excluded from both buckets,
    same exclusion _build_stage_summary already applies for unmapped stages,
    but still counted in total_leads since the lead itself is real."""
    from sqlalchemy import func, case

    day = func.date(Inquiry.created_at)
    q = (
        db.query(
            day.label("day"),
            func.count(Inquiry.id).label("total"),
            func.coalesce(func.sum(case((PipelineStage.category == "valid", 1), else_=0)), 0).label("valid"),
            func.coalesce(func.sum(case((PipelineStage.category == "invalid", 1), else_=0)), 0).label("invalid"),
            func.coalesce(func.sum(case((PipelineStage.is_closed_won.is_(True), 1), else_=0)), 0).label("converted"),
        )
        .outerjoin(PipelineStage, PipelineStage.id == Inquiry.stage_id)
        .filter(
            Inquiry.tenant_id == tenant_id,
            Inquiry.created_at >= date_from,
            Inquiry.created_at <= date_to,
        )
        .group_by(day)
        .order_by(day)
    )
    return [
        {
            "date": str(row.day),
            "total_leads": row.total,
            "valid": row.valid,
            "invalid": row.invalid,
            "converted": row.converted,
        }
        for row in q.all()
    ]


# ── Needs action (Leads default view) ─────────────────────────────────────────

# Most urgent first -- a lead lands in the first bucket that applies, so it
# never shows up twice. A ready AI draft outranks "waiting" because sending
# it IS the reply; a phone number outranks the AI's soft follow-up flag
# because a call resolves that flag too.
NEEDS_ACTION_BUCKETS = ("draft_ready", "waiting", "call", "followup")
_NEEDS_ACTION_CANDIDATES = 400
_NEEDS_ACTION_PER_BUCKET = 30
# A guest silent-on-our-side for longer than this is no longer actionable
# from here: Meta's messaging window for a human reply on WhatsApp/Instagram
# closes at 7 days at most. Measured on Ratha: without this, a 48-day-old
# WhatsApp thread topped the "waiting" list.
_WAITING_MAX_SECONDS = 7 * 86400


def _batch_spoken_since(
    db: Session, tenant_id: str, inquiries: list[Inquiry],
) -> set[str]:
    """Inquiry ids whose guest has had a real phone conversation since the
    inquiry was created: any outbound call, or an inbound call that wasn't
    missed. One query over the page's guests, no N+1."""
    from app.models.call import Call, CallDirection
    from app.services.call_status_service import is_missed_call

    by_guest: dict[str, list[Inquiry]] = {}
    for inq in inquiries:
        if inq.guest_id:
            by_guest.setdefault(inq.guest_id, []).append(inq)
    if not by_guest:
        return set()

    earliest = min(_aware_dt(i.created_at) for i in inquiries if i.created_at) if inquiries else None
    q = db.query(Call).filter(Call.tenant_id == tenant_id, Call.guest_id.in_(list(by_guest)))
    if earliest:
        q = q.filter(Call.created_at >= earliest)

    spoken: set[str] = set()
    for call in q.all():
        if call.direction != CallDirection.OUTBOUND and is_missed_call(call):
            continue
        call_at = _aware_dt(call.created_at)
        for inq in by_guest.get(call.guest_id, []):
            if inq.created_at is None or call_at >= _aware_dt(inq.created_at):
                spoken.add(inq.id)
    return spoken


def _aware_dt(dt: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes even for timezone=True columns
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_needs_action(
    db: Session,
    tenant_id: str,
    scope_user_id: Optional[str] = None,
    window_days: int = 14,
) -> NeedsActionResponse:
    """Open leads touched in the last `window_days`, grouped by what an agent
    should do next. Reuses the same batch helpers as the pipeline board so
    "waiting", "draft ready" and "follow-up" mean exactly what they mean on
    the cards there.

    Closed (won/lost) and unqualified inquiries are excluded. `scope_user_id`
    is the same visibility guard as get_leads_pipeline: non-owners see their
    own leads plus unclaimed ones."""
    from datetime import timedelta
    from app.services.date_presets import ist_range_to_utc, resolve_preset

    now = datetime.now(timezone.utc)
    closed_stage_ids = [
        r.id for r in db.query(PipelineStage.id).filter(
            PipelineStage.tenant_id == tenant_id,
            or_(PipelineStage.is_closed_won.is_(True), PipelineStage.is_closed_lost.is_(True)),
        ).all()
    ]

    q = (
        db.query(Inquiry)
        .options(
            joinedload(Inquiry.guest),
            joinedload(Inquiry.assigned_user),
            joinedload(Inquiry.pipeline_stage),
        )
        .filter(
            Inquiry.tenant_id == tenant_id,
            Inquiry.qualification_status != "unqualified",
            Inquiry.updated_at >= now - timedelta(days=window_days),
            Inquiry.stage.notin_([InquiryStage.LOST, InquiryStage.GHOSTED]),
        )
    )
    if closed_stage_ids:
        q = q.filter(or_(Inquiry.stage_id.is_(None), Inquiry.stage_id.notin_(closed_stage_ids)))
    if scope_user_id:
        q = q.filter(or_(Inquiry.assigned_to == scope_user_id, Inquiry.assigned_to.is_(None)))
    inquiries = q.order_by(desc(Inquiry.updated_at)).limit(_NEEDS_ACTION_CANDIDATES).all()

    ids = [inq.id for inq in inquiries]
    guest_ids = [inq.guest_id for inq in inquiries]
    completeness_map = _batch_completeness(db, tenant_id, guest_ids)
    signals_map = _batch_signals(db, tenant_id, guest_ids)
    prop_interest_map = _batch_property_interest(db, tenant_id, ids)
    response_time_map = _batch_response_time(db, tenant_id, ids, now=now)
    pending_draft_map = _batch_pending_drafts(db, tenant_id, ids)
    needs_followup_map = _batch_needs_agent_followup(db, tenant_id, ids)
    spoken = _batch_spoken_since(db, tenant_id, inquiries)

    buckets: dict[str, list[LeadCardSchema]] = {k: [] for k in NEEDS_ACTION_BUCKETS}
    from app.services.lead_quote_view import latest_for
    latest_quotes = latest_for(db, tenant_id, ids)
    for inq in inquiries:
        card = _build_lead_card(
            inq,
            completeness=completeness_map.get(inq.guest_id, 0),
            signals=signals_map.get(inq.guest_id, []),
            property_interest=prop_interest_map.get(inq.id, []),
            response_time=response_time_map.get(inq.id),
            pending_draft=pending_draft_map.get(inq.id),
            needs_agent_followup_reason=needs_followup_map.get(inq.id),
        )
        card.latest_quote = latest_quotes.get(inq.id)
        waiting = (
            card.response_time_status == "waiting"
            and (card.response_time_seconds or 0) <= _WAITING_MAX_SECONDS
        )
        # A pending draft only means "reply ready" while the guest is still
        # waiting. Once any reply went out the draft is superseded -- on
        # Ratha 9 of 10 pending drafts were leftovers from message bursts
        # the AI had already answered.
        if waiting and card.pending_draft:
            buckets["draft_ready"].append(card)
        elif waiting:
            buckets["waiting"].append(card)
        elif "phone" in (card.identity_signals or []) and inq.id not in spoken:
            buckets["call"].append(card)
        elif card.needs_agent_followup:
            buckets["followup"].append(card)

    # Longest-waiting first where waiting time means something; newest
    # enquiry first for "call" (a fresh number is the warmest lead).
    buckets["waiting"].sort(key=lambda c: -(c.response_time_seconds or 0))
    buckets["call"].sort(key=lambda c: c.created_at or now, reverse=True)

    waiting = buckets["waiting"] + buckets["draft_ready"]
    recent_cutoff = now - timedelta(days=3)
    unassigned_recent = sum(
        1 for inq in inquiries
        if inq.assigned_to is None and inq.created_at and _aware_dt(inq.created_at) >= recent_cutoff
    )
    m_from, m_to = resolve_preset("this_month")
    month_from, month_to, _, _ = ist_range_to_utc(m_from.isoformat(), m_to.isoformat())
    sold_ids = _booked_inquiry_ids(db, tenant_id, month_from, month_to)
    if scope_user_id and sold_ids:
        sold_ids = [
            r.id for r in db.query(Inquiry.id).filter(
                Inquiry.id.in_(sold_ids),
                or_(Inquiry.assigned_to == scope_user_id, Inquiry.assigned_to.is_(None)),
            ).all()
        ]

    kpis = NeedsActionKpis(
        waiting=len(waiting),
        waiting_oldest_seconds=max((c.response_time_seconds or 0 for c in waiting), default=None),
        drafts_ready=len(buckets["draft_ready"]),
        phone_not_called=len(buckets["call"]),
        unassigned_recent=unassigned_recent,
        sold_this_month=len(set(sold_ids)),
    )
    return NeedsActionResponse(
        window_days=window_days,
        kpis=kpis,
        buckets=[
            NeedsActionBucket(key=k, total=len(buckets[k]), leads=buckets[k][:_NEEDS_ACTION_PER_BUCKET])
            for k in NEEDS_ACTION_BUCKETS
        ],
    )
