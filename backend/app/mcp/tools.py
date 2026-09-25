"""MCP tool definitions for HAIP's external-assistant integration (Perisclaw).

Each tool wraps an EXISTING endpoint/service function, calling it as a plain
Python function with an explicitly-resolved User + Session (FastAPI route
functions are just regular functions -- Depends(...) defaults only apply
when invoked over real HTTP; calling them directly with real arguments
works fine and avoids duplicating logic).

Every handler receives (db, user, tenant_id, arguments) and must be called
against a session that already had set_tenant_context() applied by the
caller (see server.py) -- these functions run outside FastAPI's per-request
dependency cycle, same as a Celery task, so RLS context has to be
established explicitly rather than relying on a request-scoped dependency.
"""
from typing import Any, Optional
from sqlalchemy.orm import Session

from app.mcp import redaction
from app.models.user import User


class ToolError(Exception):
    """Raised by a tool handler for a user-facing error (maps to MCP isError)."""


# 3.6: every write tool's inputSchema advertises these two params -- actual
# enforcement (block until confirm:true, dedup on idempotency_key for 24h)
# lives in server.py's tools/call dispatch, applied uniformly to every tool
# whose annotations.readOnlyHint is False. Merge this into a write tool's
# own `properties`/`required` rather than duplicating it by hand.
_CONFIRM_PROPS = {
    "confirm": {"type": "boolean", "description": "Must be true -- this is a real write action."},
    "idempotency_key": {"type": "string", "description": "Any client-generated unique string identifying this specific action; retries with the same key are deduped for 24h."},
}
_CONFIRM_REQUIRED = ["confirm", "idempotency_key"]


def _write_schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {**properties, **_CONFIRM_PROPS},
        "required": [*required, *_CONFIRM_REQUIRED],
    }


def _dump(obj) -> Any:
    if isinstance(obj, list):
        return [_dump(o) for o in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__table__"):
        # Raw SQLAlchemy ORM instance (e.g. list_guests has no
        # response_model -- over real HTTP, FastAPI's jsonable_encoder
        # handles this implicitly; called directly like every other tool
        # here, that pipeline is bypassed, so column values need pulling
        # out explicitly or the caller gets `str(guest_object)` and no
        # actual data at all).
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    return obj


# ── Read tools ──────────────────────────────────────────────────────────────

def _list_recent_conversations(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.conversations import list_conversations
    result = list_conversations(
        channel=args.get("channel"),
        is_open=args.get("is_open"),
        sort=args.get("sort", "smart"),
        limit=args.get("limit", 20),
        before=None,
        current_user=user,
        db=db,
    )
    return _dump(result)


def _get_conversation_thread(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.conversations import get_conversation_detail
    from fastapi import HTTPException
    try:
        result = get_conversation_detail(conversation_id=args["conversation_id"], current_user=user, db=db)
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc
    # 3.3: message bodies are guest-authored, attacker-controlled text.
    return redaction.wrap_untrusted(_dump(result), key="conversation")


def _search_conversations(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.conversations import search_conversations
    result = search_conversations(q=args["query"], limit=args.get("limit", 20), current_user=user, db=db)
    return redaction.wrap_untrusted(_dump(result), key="results")


def _visibility_scope(user: User) -> Optional[str]:
    """Same guard as leads.py's endpoint -- Ask HAIP must not let a non-owner/
    manager agent list or open a peer agent's lead just because the UI-level
    restriction doesn't apply to a tool call."""
    from app.models.user import UserRole
    if user.role in (UserRole.OWNER, UserRole.MANAGER):
        return None
    return user.id


def _list_leads(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.services.date_presets import VALID_PRESETS, resolve_range
    from app.services.leads_service import get_leads_pipeline
    preset = args.get("enquiry_date_preset")
    checkin_preset = args.get("checkin_date_preset")
    for value in (preset, checkin_preset):
        if value and value not in VALID_PRESETS:
            raise ToolError(f"Unknown date preset {value!r}. Use one of: {', '.join(sorted(VALID_PRESETS))}")
    try:
        # Presets resolve in IST, same as the Leads360 page.
        date_from, date_to = resolve_range(preset, args.get("date_from"), args.get("date_to"))
        checkin_from, checkin_to = resolve_range(checkin_preset, args.get("checkin_date_from"), args.get("checkin_date_to"))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    result = get_leads_pipeline(
        db,
        tenant_id=tenant_id,
        stage=args.get("stage"),
        property_id=args.get("property_id"),
        assigned_to=args.get("assigned_to"),
        source=args.get("source"),
        date_from=date_from,
        date_to=date_to,
        checkin_date_from=checkin_from,
        checkin_date_to=checkin_to,
        page=args.get("page", 1),
        page_size=min(int(args.get("page_size", 25)), 100),
        scope_user_id=_visibility_scope(user),
    )
    return _dump(result)


def _get_lead_detail(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.services.leads_service import get_lead_detail
    result = get_lead_detail(
        db, tenant_id=tenant_id, inquiry_id=args["inquiry_id"],
        scope_user_id=_visibility_scope(user),
    )
    if result is None:
        raise ToolError(f"Lead {args['inquiry_id']} not found")
    return _dump(result)


def _search_guests(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.guests import list_guests
    # Every Query()-defaulted parameter must be passed explicitly: called
    # outside FastAPI, an omitted one arrives as the Query(None) object
    # itself, which is truthy -- `phone` did exactly that and broke this
    # tool for every call once list_guests gained it.
    result = list_guests(
        search=args.get("query"),
        phone=None,
        limit=min(int(args.get("limit", 20)), 200),
        offset=0,
        current_user=user,
        db=db,
    )
    return _dump(result)


def _reveal_guest_contact(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    """3.2: the one tool that deliberately returns UNMASKED phone/email --
    gated on guests.pii.reveal and given its own distinct audit action
    (mcp.pii.reveal, see server.py) rather than the generic
    mcp.tool.<name> pattern, since this is specifically the DPDP paper
    trail the plan requires (§4.2)."""
    from app.models.guest import Guest
    guest = db.query(Guest).filter_by(id=args["guest_id"], tenant_id=tenant_id, is_deleted=False).first()
    if not guest:
        raise ToolError(f"Guest {args['guest_id']!r} not found")
    return {"guest_id": guest.id, "name": guest.name, "phone": guest.phone, "email": guest.email}


def _check_module(db: Session, user: User, *module_codes: str) -> None:
    """Some wrapped endpoints gate on workspace_context.active_modules (a
    plan-tier/billing entitlement, separate from the capability-registry
    RBAC axis Phase 1/2 built). Calling the endpoint function directly
    skips its Depends(require_module(...)) chain the same way it already
    skips Depends(get_current_user)/Depends(get_db) defaults -- resolve it
    explicitly here rather than silently letting a tool bypass a paid-tier
    gate the REST equivalent enforces."""
    from app.api.v1.deps import get_workspace_context
    ctx = get_workspace_context(current_user=user, db=db)
    missing = [m for m in module_codes if m not in ctx.active_modules]
    if missing:
        raise ToolError(f"This feature requires modules: {', '.join(missing)}. Contact your HAIP account manager to upgrade.")


def _list_calls(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.calls import list_calls
    result = list_calls(
        page=args.get("page", 1), limit=args.get("limit", 20),
        direction=args.get("direction"), agent_id=args.get("agent_id"),
        guest_id=args.get("guest_id"), missed=args.get("missed"),
        date_preset=args.get("date_preset"), date_from=args.get("date_from"), date_to=args.get("date_to"),
        db=db, current_user=user,
    )
    return _dump(result)


def _get_call_analysis(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.calls import get_call
    from fastapi import HTTPException
    try:
        detail = get_call(call_id=args["call_id"], db=db, current_user=user)
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc
    return {
        "id": detail["id"],
        "disposition": detail["disposition"],
        "ai_summary": detail["ai_summary"],
        "ai_next_action": detail["ai_next_action"],
        "recommended_actions": detail.get("recommended_actions"),
        "score": detail["score"],
        "layer2": detail["layer2"],
    }


def _get_call_transcript(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.calls import get_call
    from fastapi import HTTPException
    try:
        detail = get_call(call_id=args["call_id"], db=db, current_user=user)
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc
    # 3.3: transcript text is the guest's own recorded speech -- same
    # untrusted-content class as message bodies.
    return redaction.wrap_untrusted(
        {"call_id": detail["id"], "transcript": detail["transcript"], "transcript_text": detail["transcript_text"]},
        key="transcript",
    )


def _list_bookings(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.bookings import list_bookings
    result = list_bookings(
        search=args.get("search"), status=args.get("status"), channel=args.get("channel"),
        sort=args.get("sort", "newest"), page=args.get("page", 1), per_page=args.get("per_page", 25),
        guest_id=args.get("guest_id"), date_preset=args.get("date_preset"),
        date_from=args.get("date_from"), date_to=args.get("date_to"),
        current_user=user, db=db,
    )
    return _dump(result)


def _get_revenue_summary(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    _check_module(db, user, "analytics")
    from app.api.v1.endpoints.analytics_executive import executive_dashboard
    detail = _dump(executive_dashboard(
        range_days=args.get("range_days", 30), property_ids=args.get("property_ids"),
        current_user=user, db=db,
    ))
    return {
        "revenue_mtd": detail["revenue_mtd"],
        "revenue_mtd_prev": detail["revenue_mtd_prev"],
        "revenue_chart": detail["revenue_chart"],
    }


def _get_dashboard_metrics(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    _check_module(db, user, "analytics")
    from app.api.v1.endpoints.analytics_executive import executive_dashboard
    result = executive_dashboard(
        range_days=args.get("range_days", 30), property_ids=args.get("property_ids"),
        current_user=user, db=db,
    )
    return _dump(result)


def _get_agent_scorecard(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    _check_module(db, user, "calls")
    from app.api.v1.endpoints.analytics import personal_scorecard
    result = personal_scorecard(period=args.get("period", "this_week"), current_user=user, db=db)
    return _dump(result)


async def _ask_haip(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.models.user import UserRole
    # ask_freeform_endpoint (the REST equivalent) is explicitly owner-only
    # "for this initial rollout ... expand roles once real usage/audit logs
    # have been reviewed" -- MCP access being owner/manager-only doesn't
    # override that narrower, deliberate product decision.
    if user.role != UserRole.OWNER:
        raise ToolError("Ask HAIP free-form analyst is owner-only for this rollout.")
    _check_module(db, user, "ask_haip")
    from app.services.ask_haip_freeform_service import answer_freeform_question
    question = (args.get("question") or "").strip()
    if not question:
        raise ToolError("question is required")
    result = await answer_freeform_question(db=db, tenant_id=tenant_id, user_id=user.id, question=question)
    return _dump(result)


def _check_availability(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    """AI Autonomy Plan Phase 1, ticket 3. Wraps CalculatorService.search()
    -- the same function backing POST /calculator/search -- which already
    resolves rates (seasonal > rate plan > base, including live RentalWise
    rates for channel-managed properties) AND filters out any property
    with a confirmed Stay or active BlockedDate overlapping the requested
    dates. The plan lists RentalWise as a separate data source this tool
    needs; it's actually already folded into this same search path."""
    from dataclasses import asdict
    from app.services.calculator_service import calculator_service

    results = calculator_service.search(
        db=db, tenant_id=tenant_id,
        checkin=args["from_date"], checkout=args["to_date"],
        adults=args.get("adults", 1), children=args.get("children", 0),
        city=args.get("city"), property_id=args.get("property_id"),
        property_type=args.get("property_type"),
    )
    return {
        "checkin": args["from_date"],
        "checkout": args["to_date"],
        "matching_properties": [asdict(r) for r in results],
        "note": (
            "Only properties with a resolved rate AND no booking/block "
            "conflict for these exact dates and party size are returned. "
            "An empty list means nothing is available -- do not assume "
            "availability for any property not in this list."
        ),
    }


def _get_quote(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    """AI Autonomy Plan Phase 1, ticket 3. Wraps CalculatorService.build_quote()
    -- the actual guest-facing quote path (POST /calculator/quote), which
    includes GST and advance-amount breakdown. NOTE: this does NOT call
    dynamic_pricing_service, despite the plan listing both together --
    verified against the real code: build_quote() never references it, and
    the REST /calculator/dynamic-price endpoint is a wholly separate,
    unconnected revenue-management path. This tool reflects what a guest
    would actually be quoted today, not a theoretical merge of the two."""
    from dataclasses import asdict
    from app.services.calculator_service import calculator_service

    quote = calculator_service.build_quote(
        db=db, tenant_id=tenant_id, property_id=args["property_id"],
        checkin=args["from_date"], checkout=args["to_date"],
        adults=args.get("adults", 1), children=args.get("children", 0),
        selected_addon_ids=args.get("addon_ids"),
        advance_percent=args.get("advance_percent", 30),
    )
    if quote is None:
        raise ToolError(
            "No quote available for this property/date range -- either the "
            "property has no rate configured, party size exceeds capacity, "
            "or the dates are unavailable. Use check_availability first."
        )
    return asdict(quote)


# ── Write tools ─────────────────────────────────────────────────────────────

def _approve_and_send_draft(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.conversations import approve_ai_draft
    from fastapi import HTTPException
    try:
        return approve_ai_draft(
            conversation_id=args["conversation_id"], message_id=args["message_id"], current_user=user, db=db,
        )
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc


def _move_lead_stage(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.services.inquiry_service import update_stage_by_id, InvalidStageTransition
    try:
        inquiry = update_stage_by_id(
            db,
            tenant_id=tenant_id,
            inquiry_id=args["inquiry_id"],
            new_stage_id=args["new_stage_id"],
            actor_user_id=user.id,
            actor_role=user.role.value if hasattr(user.role, "value") else str(user.role),
            reason=args.get("reason"),
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except InvalidStageTransition as exc:
        raise ToolError(exc.detail) from exc
    return {"inquiry_id": inquiry.id, "stage_id": inquiry.stage_id}


def _add_note(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.inquiries import add_inquiry_note, NoteRequest
    from fastapi import HTTPException
    try:
        return add_inquiry_note(
            inquiry_id=args["inquiry_id"], body=NoteRequest(body=args["note"]), current_user=user, db=db,
        )
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc


def _assign_lead(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.inquiries import update_inquiry
    from app.schemas.inquiry import InquiryUpdateRequest
    from fastapi import HTTPException
    try:
        result = update_inquiry(
            inquiry_id=args["inquiry_id"], body=InquiryUpdateRequest(assigned_to=args["assigned_to"]),
            current_user=user, db=db,
        )
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc
    return _dump(result)


# Deliberately excludes stage/stage_id (move_lead_stage's job, state-machine
# guarded) and assigned_to (assign_lead's job) -- one write tool per concern
# keeps each tool's blast radius narrow and its capability check meaningful.
_UPDATABLE_LEAD_FIELDS = {
    "property_id", "lost_reason", "lost_note", "check_in", "check_out",
    "adults", "children", "occasion", "budget", "quoted_amount",
}


def _update_lead_fields(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.inquiries import update_inquiry
    from app.schemas.inquiry import InquiryUpdateRequest
    from fastapi import HTTPException
    fields = args.get("fields") or {}
    unknown = set(fields) - _UPDATABLE_LEAD_FIELDS
    if unknown:
        raise ToolError(
            f"Unsupported field(s): {', '.join(sorted(unknown))}. "
            "Use move_lead_stage for stage changes and assign_lead for assignment."
        )
    try:
        result = update_inquiry(inquiry_id=args["inquiry_id"], body=InquiryUpdateRequest(**fields), current_user=user, db=db)
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc
    return _dump(result)


def _add_guest_signal(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.services import identity_service
    try:
        confidence = identity_service.add_signal(
            db, tenant_id=tenant_id, guest_id=args["guest_id"], signal_type=args["signal_type"],
            value=args["value"], source="mcp", actor_user_id=user.id,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    db.commit()
    # Deliberately not echoing the raw value back -- the caller already has
    # it (they just sent it); no reason to round-trip PII through the
    # response too.
    return {"guest_id": args["guest_id"], "signal_type": args["signal_type"], "confidence": confidence}


# create_task: NOT implemented. The plan lists this as a Phase 3 write
# tool, but no Task model/service exists anywhere in this codebase (only
# `add_note`'s free-text inquiry notes) -- building one is a net-new
# feature (model + migration + RLS + service), not something this
# MCP-hardening plan's own scope covers, and CLAUDE.md is explicit against
# expanding scope on a plan like this one without being asked. Skipped;
# flagged for the user to decide whether it's worth a separate ticket.


# ── Tool registry ────────────────────────────────────────────────────────────
# annotations.readOnlyHint tells the MCP client (Perisclaw) which tools are
# safe to call without a real-action confirmation prompt (their own
# guardrail, documented at docs.perisclaw.com/skills-and-integrations).

TOOLS: list[dict] = [
    {
        "name": "list_recent_conversations",
        "description": "List recent WhatsApp/Instagram conversations (inbox), newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Filter by channel, e.g. whatsapp, instagram"},
                "is_open": {"type": "boolean", "description": "Filter by open/resolved status"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        "annotations": {"readOnlyHint": True},
        "capability": "conversations.read",
        "handler": _list_recent_conversations,
    },
    {
        "name": "get_conversation_thread",
        "description": "Get the full message thread for a conversation, including AI-draft state.",
        "inputSchema": {
            "type": "object",
            "properties": {"conversation_id": {"type": "string"}},
            "required": ["conversation_id"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "conversations.read",
        "handler": _get_conversation_thread,
    },
    {
        "name": "search_conversations",
        "description": "Full-text search across all message content for this tenant.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 20}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "conversations.read",
        "handler": _search_conversations,
    },
    {
        "name": "list_leads",
        "description": (
            "List Leads360 pipeline cards (one per enquiry), with a total count. Filter by "
            "stage, source, assignee, property, enquiry date or check-in date (IST). "
            "For counts by source/stage over a period, page through with page_size=100."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "description": "Pipeline stage key to filter by"},
                "source": {"type": "string", "description": "e.g. wa_direct, meta_ig, click_to_wa, inbound_call"},
                "assigned_to": {"type": "string", "description": "User id of the assigned agent"},
                "property_id": {"type": "string"},
                "enquiry_date_preset": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_month", "last_month", "last_7d", "last_14d", "custom"],
                },
                "date_from": {"type": "string", "description": "Enquiry date YYYY-MM-DD, with enquiry_date_preset=custom"},
                "date_to": {"type": "string", "description": "Enquiry date YYYY-MM-DD, with enquiry_date_preset=custom"},
                "checkin_date_preset": {
                    "type": "string",
                    "enum": ["next_7d", "next_14d", "last_7d", "last_14d", "this_month", "custom"],
                },
                "checkin_date_from": {"type": "string", "description": "YYYY-MM-DD, with checkin_date_preset=custom"},
                "checkin_date_to": {"type": "string", "description": "YYYY-MM-DD, with checkin_date_preset=custom"},
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 25, "maximum": 100},
            },
        },
        "annotations": {"readOnlyHint": True},
        "capability": "leads.read",
        "handler": _list_leads,
    },
    {
        "name": "get_lead_detail",
        "description": "Get full detail for one lead/inquiry, including timeline and quote history.",
        "inputSchema": {
            "type": "object",
            "properties": {"inquiry_id": {"type": "string"}},
            "required": ["inquiry_id"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "leads.read",
        "handler": _get_lead_detail,
    },
    {
        "name": "search_guests",
        "description": "Search guests by name, phone, or email.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 20}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "guests.read",
        "handler": _search_guests,
    },
    {
        "name": "reveal_guest_contact",
        "description": "Reveal a guest's unmasked phone/email (masked by default everywhere else). Every call is separately audited (mcp.pii.reveal) -- use only when the raw contact info is actually needed.",
        "inputSchema": {
            "type": "object",
            "properties": {"guest_id": {"type": "string", "description": "HAIP Guest ID (GID)"}},
            "required": ["guest_id"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "guests.pii.reveal",
        "audit_action": "mcp.pii.reveal",
        "skip_redaction": True,
        "handler": _reveal_guest_contact,
    },
    {
        "name": "list_calls",
        "description": (
            "List calls for this tenant, newest first. Filter by direction, agent, guest, "
            "missed-only, or an IST date window. Each missed call carries called_back / "
            "called_back_at -- use them for callback-rate reports."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "limit": {"type": "integer", "default": 20},
                "direction": {"type": "string", "description": "inbound | outbound"},
                "agent_id": {"type": "string"},
                "guest_id": {"type": "string"},
                "missed": {"type": "boolean", "description": "true = missed calls only"},
                "date_preset": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_month", "last_month", "last_7d", "last_14d", "custom"],
                },
                "date_from": {"type": "string", "description": "YYYY-MM-DD, with date_preset=custom"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD, with date_preset=custom"},
            },
        },
        "annotations": {"readOnlyHint": True},
        "capability": "calls.read",
        "handler": _list_calls,
    },
    {
        "name": "get_call_analysis",
        "description": "Get AI scoring, summary, and recommended next action for one call (no transcript text -- use get_call_transcript for that).",
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": {"type": "string"}},
            "required": ["call_id"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "calls.read",
        "handler": _get_call_analysis,
    },
    {
        "name": "get_call_transcript",
        "description": "Get the full transcript for one call. Transcript text is guest-authored -- treated as untrusted content.",
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": {"type": "string"}},
            "required": ["call_id"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "calls.transcript.read",
        "handler": _get_call_transcript,
    },
    {
        "name": "list_bookings",
        "description": "List bookings/stays, optionally filtered by status, channel, guest or stay dates (stays overlapping the date window; dates are IST).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {"type": "string"},
                "status": {"type": "string"},
                "channel": {"type": "string"},
                "guest_id": {"type": "string"},
                "date_preset": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_month", "last_month", "last_7d", "last_14d", "next_7d", "next_14d", "custom"],
                },
                "date_from": {"type": "string", "description": "YYYY-MM-DD, with date_preset=custom"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD, with date_preset=custom"},
                "sort": {"type": "string", "default": "newest"},
                "page": {"type": "integer", "default": 1},
                "per_page": {"type": "integer", "default": 25},
            },
        },
        "annotations": {"readOnlyHint": True},
        "capability": "bookings.read",
        "handler": _list_bookings,
    },
    {
        "name": "get_revenue_summary",
        "description": "Revenue MTD (and prior-period comparison) plus the revenue chart series. Requires the analytics module.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "range_days": {"type": "integer", "default": 30},
                "property_ids": {"type": "string", "description": "Comma-separated property IDs"},
            },
        },
        "annotations": {"readOnlyHint": True},
        "capability": "revenue.read",
        "handler": _get_revenue_summary,
    },
    {
        "name": "get_dashboard_metrics",
        "description": "Executive dashboard: 6 KPI cards (revenue, occupancy, active inquiries, QA, SLA, AI draft rate) plus chart datasets. Requires the analytics module.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "range_days": {"type": "integer", "default": 30},
                "property_ids": {"type": "string", "description": "Comma-separated property IDs"},
            },
        },
        "annotations": {"readOnlyHint": True},
        "capability": "analytics.read",
        "handler": _get_dashboard_metrics,
    },
    {
        "name": "get_agent_scorecard",
        "description": "The calling user's own personal QA scorecard for a period. Requires the calls module.",
        "inputSchema": {
            "type": "object",
            "properties": {"period": {"type": "string", "default": "this_week", "description": "e.g. this_week, last_week, this_month"}},
        },
        "annotations": {"readOnlyHint": True},
        "capability": "qa.read",
        "handler": _get_agent_scorecard,
    },
    {
        "name": "ask_haip",
        "description": "Ask HAIP's free-form analyst any ad-hoc business question (NL -> SQL against a read-only role). Owner-only, requires the ask_haip module.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "analytics.read",
        "handler": _ask_haip,
    },
    {
        "name": "check_availability",
        "description": "Check which properties are available for given dates and party size, with resolved rates. Only returns properties with a real rate AND no booking/block conflict for the exact dates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_date": {"type": "string", "description": "Check-in date, YYYY-MM-DD"},
                "to_date": {"type": "string", "description": "Check-out date, YYYY-MM-DD"},
                "adults": {"type": "integer", "default": 1},
                "children": {"type": "integer", "default": 0},
                "property_id": {"type": "string", "description": "Restrict to one property"},
                "city": {"type": "string"},
                "property_type": {"type": "string", "description": "villa | caravan | hotel | apartment"},
            },
            "required": ["from_date", "to_date"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "bookings.read",
        "handler": _check_availability,
    },
    {
        "name": "get_quote",
        "description": "Build a real, bookable quote for one property -- accommodation + selected add-ons + GST + advance amount. Call check_availability first to find a valid property_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "from_date": {"type": "string", "description": "Check-in date, YYYY-MM-DD"},
                "to_date": {"type": "string", "description": "Check-out date, YYYY-MM-DD"},
                "adults": {"type": "integer", "default": 1},
                "children": {"type": "integer", "default": 0},
                "addon_ids": {"type": "array", "items": {"type": "string"}, "description": "Selected add-on IDs from the property's addon list"},
                "advance_percent": {"type": "integer", "default": 30},
            },
            "required": ["property_id", "from_date", "to_date"],
        },
        "annotations": {"readOnlyHint": True},
        "capability": "revenue.read",
        "handler": _get_quote,
    },
    {
        "name": "approve_and_send_draft",
        "description": "Approve and send a pending AI-drafted WhatsApp reply. This is a real action -- confirm with the user before calling. Requires confirm:true and idempotency_key.",
        "inputSchema": _write_schema(
            {"conversation_id": {"type": "string"}, "message_id": {"type": "string"}},
            ["conversation_id", "message_id"],
        ),
        # A sent WhatsApp message can't be unsent -- genuinely irreversible,
        # unlike the other write tools here.
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
        "capability": "conversations.send",
        "handler": _approve_and_send_draft,
    },
    {
        "name": "move_lead_stage",
        "description": "Move a lead/inquiry to a different pipeline stage. This is a real action -- confirm with the user before calling. Moving backward requires a reason and owner/manager role. Requires confirm:true and idempotency_key.",
        "inputSchema": _write_schema(
            {
                "inquiry_id": {"type": "string"},
                "new_stage_id": {"type": "string"},
                "reason": {"type": "string", "description": "Required for backward moves"},
            },
            ["inquiry_id", "new_stage_id"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "capability": "leads.write",
        "handler": _move_lead_stage,
    },
    {
        "name": "add_note",
        "description": "Add an internal note to a lead/inquiry. This is a real action -- confirm with the user before calling. Requires confirm:true and idempotency_key.",
        "inputSchema": _write_schema(
            {"inquiry_id": {"type": "string"}, "note": {"type": "string"}},
            ["inquiry_id", "note"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "capability": "leads.write",
        "handler": _add_note,
    },
    {
        "name": "assign_lead",
        "description": "Assign a lead/inquiry to a team member. This is a real action -- confirm with the user before calling. Requires confirm:true and idempotency_key.",
        "inputSchema": _write_schema(
            {"inquiry_id": {"type": "string"}, "assigned_to": {"type": "string", "description": "User ID of the assignee"}},
            ["inquiry_id", "assigned_to"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "capability": "leads.write",
        "handler": _assign_lead,
    },
    {
        "name": "update_lead_fields",
        "description": (
            "Update descriptive fields on a lead/inquiry (property, dates, occasion, budget, quoted amount, "
            "lost reason). Not for stage (use move_lead_stage) or assignment (use assign_lead). "
            "This is a real action -- confirm with the user before calling. Requires confirm:true and idempotency_key."
        ),
        "inputSchema": _write_schema(
            {
                "inquiry_id": {"type": "string"},
                "fields": {
                    "type": "object",
                    "description": f"Any of: {', '.join(sorted(_UPDATABLE_LEAD_FIELDS))}",
                },
            },
            ["inquiry_id", "fields"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "capability": "leads.write",
        "handler": _update_lead_fields,
    },
    {
        "name": "add_guest_signal",
        "description": (
            "Add an identity signal (phone, email, etc.) to a guest -- auto-writes DPDP consent for PII "
            "signal types. Can trigger identity-resolution merge detection as a side effect. This is a real "
            "action -- confirm with the user before calling. Requires confirm:true and idempotency_key."
        ),
        "inputSchema": _write_schema(
            {
                "guest_id": {"type": "string", "description": "HAIP Guest ID (GID)"},
                "signal_type": {"type": "string", "description": "e.g. phone, email, whatsapp_number, instagram"},
                "value": {"type": "string"},
            },
            ["guest_id", "signal_type", "value"],
        ),
        # Can trigger a silent guest-identity merge via enrich_guest's merge
        # detection -- treat as destructive even though it's framed as an
        # additive "add a signal" action.
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
        "capability": "leads.write",  # no dedicated guests.write key in the v1 catalogue (§2.2) -- this is the closest fit, documented gap.
        "handler": _add_guest_signal,
    },
]

TOOLS_BY_NAME: dict[str, dict] = {t["name"]: t for t in TOOLS}
