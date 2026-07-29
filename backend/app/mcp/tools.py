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
from typing import Any
from sqlalchemy.orm import Session

from app.models.user import User


class ToolError(Exception):
    """Raised by a tool handler for a user-facing error (maps to MCP isError)."""


def _dump(obj) -> Any:
    if isinstance(obj, list):
        return [_dump(o) for o in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


# ── Read tools ──────────────────────────────────────────────────────────────

def _list_recent_conversations(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.conversations import list_conversations
    result = list_conversations(
        channel=args.get("channel"),
        is_open=args.get("is_open"),
        sort=args.get("sort", "smart"),
        limit=args.get("limit", 20),
        current_user=user,
        db=db,
    )
    return _dump(result)


def _get_conversation_thread(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.conversations import get_conversation_detail
    from fastapi import HTTPException
    try:
        return get_conversation_detail(conversation_id=args["conversation_id"], current_user=user, db=db)
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc


def _search_conversations(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.conversations import search_conversations
    return search_conversations(q=args["query"], limit=args.get("limit", 20), current_user=user, db=db)


def _list_leads(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.services.leads_service import get_leads_pipeline
    result = get_leads_pipeline(
        db,
        tenant_id=tenant_id,
        stage=args.get("stage"),
        page=args.get("page", 1),
        page_size=args.get("page_size", 25),
    )
    return _dump(result)


def _get_lead_detail(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.services.leads_service import get_lead_detail
    result = get_lead_detail(db, tenant_id=tenant_id, inquiry_id=args["inquiry_id"])
    if result is None:
        raise ToolError(f"Lead {args['inquiry_id']} not found")
    return _dump(result)


def _search_guests(db: Session, user: User, tenant_id: str, args: dict) -> Any:
    from app.api.v1.endpoints.guests import list_guests
    result = list_guests(
        search=args.get("query"),
        limit=args.get("limit", 20),
        offset=0,
        current_user=user,
        db=db,
    )
    return _dump(result)


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
        "handler": _search_conversations,
    },
    {
        "name": "list_leads",
        "description": "List Leads360 pipeline cards, optionally filtered by stage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "description": "Pipeline stage key to filter by"},
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 25},
            },
        },
        "annotations": {"readOnlyHint": True},
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
        "handler": _search_guests,
    },
    {
        "name": "approve_and_send_draft",
        "description": "Approve and send a pending AI-drafted WhatsApp reply. This is a real action -- confirm with the user before calling.",
        "inputSchema": {
            "type": "object",
            "properties": {"conversation_id": {"type": "string"}, "message_id": {"type": "string"}},
            "required": ["conversation_id", "message_id"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "handler": _approve_and_send_draft,
    },
    {
        "name": "move_lead_stage",
        "description": "Move a lead/inquiry to a different pipeline stage. This is a real action -- confirm with the user before calling. Moving backward requires a reason and owner/manager role.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "inquiry_id": {"type": "string"},
                "new_stage_id": {"type": "string"},
                "reason": {"type": "string", "description": "Required for backward moves"},
            },
            "required": ["inquiry_id", "new_stage_id"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "handler": _move_lead_stage,
    },
    {
        "name": "add_note",
        "description": "Add an internal note to a lead/inquiry. This is a real action -- confirm with the user before calling.",
        "inputSchema": {
            "type": "object",
            "properties": {"inquiry_id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["inquiry_id", "note"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "handler": _add_note,
    },
]

TOOLS_BY_NAME: dict[str, dict] = {t["name"]: t for t in TOOLS}
