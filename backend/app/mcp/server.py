"""Hand-rolled MCP (Model Context Protocol) HTTP transport for HAIP.

Why not the official `mcp` SDK: every recent release requires
pydantic>=2.11, but HAIP's entire backend is pinned to pydantic==2.10.3
(hundreds of existing schemas). Bumping that for one personal integration
is a disproportionate blast radius, so this implements just the transport
surface we actually need -- JSON-RPC 2.0 over a single POST endpoint,
methods `initialize`, `tools/list`, `tools/call` -- with zero new
dependencies. Stateless: the Bearer token is re-verified on every request
instead of tracking an Mcp-Session-Id, since none of our tools need
server-initiated push or multi-turn elicitation.

Auth: Authorization: Bearer <personal-access-token>, verified against
token_service.verify_token(). Resolves to a real (User, tenant_id) pair,
same as a normal HAIP login -- these tools call existing endpoint/service
functions directly using that identity.
"""
import hashlib
import inspect
import time

from fastapi import APIRouter, Request, Response
import structlog

from app.core import cache
from app.core.audit import append_audit
from app.core.database import SessionLocal, set_tenant_context
from app.mcp import redaction
from app.models.user import User, UserRole
from app.services import authz_service, token_service
from app.mcp.tools import TOOLS, TOOLS_BY_NAME, ToolError

log = structlog.get_logger()
router = APIRouter(prefix="/mcp", tags=["mcp"])

_PROTOCOL_VERSION = "2024-11-05"

# Locked 2026-08-02 (HAIP_MCP_Connector_Plan.md §1.1): access is owner/manager
# only until the capability registry (Phase 1) lands. Widening this to a
# third role without Phase 1 first recreates the exact "second source of
# truth" drift the plan exists to prevent -- see the plan's §6 sequencing
# note before changing this set.
_MCP_ALLOWED_ROLES = {UserRole.OWNER, UserRole.MANAGER}

# 0.3: json.dumps of a full tool result is unbounded -- a long call
# transcript or a 50-message thread can blow the client's context window
# and cost. Truncate the serialized text, not the underlying data structure
# (truncating mid-object risks invalid JSON in the text payload).
_MAX_RESULT_CHARS = 40_000


def _jsonrpc_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _jsonrpc_result(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


@router.post("")
async def mcp_endpoint(request: Request):
    body = await request.json()
    request_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return _jsonrpc_result(request_id, {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "haip-mcp", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        # Client notification, no response body expected.
        return Response(status_code=202)

    # Every method beyond initialize requires a valid PAT.
    auth_header = request.headers.get("authorization", "")
    raw_token = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""

    db = SessionLocal()
    try:
        token_record = token_service.verify_token(db, raw_token)
        if not token_record:
            return _jsonrpc_error(request_id, -32001, "Unauthorized: invalid or revoked token")

        set_tenant_context(db, token_record.tenant_id)
        # D1: the PAT itself being valid isn't enough -- a deactivated or
        # soft-deleted user must lose MCP access the same request their
        # access would 401 on the normal web login, not on some later
        # cache-expiry cycle. Offboarding an agent used to leave their
        # Claude connector working indefinitely.
        user = db.query(User).filter_by(
            id=token_record.user_id, tenant_id=token_record.tenant_id,
            is_active=True, is_deleted=False,
        ).first()
        if not user:
            log.warning("mcp_auth_denied_inactive_user", user_id=token_record.user_id, tenant_id=token_record.tenant_id)
            return _jsonrpc_error(request_id, -32001, "Unauthorized: token's user no longer exists or is deactivated")

        # 0.7: the issuance gate (owner/manager-only PAT creation) is not
        # sufficient on its own -- a user demoted from manager to concierge
        # *keeps a valid PAT*, same bug class as D1. Re-check on every
        # request, not just at token creation time.
        if user.role not in _MCP_ALLOWED_ROLES:
            log.warning("mcp_auth_denied_role", user_id=user.id, tenant_id=token_record.tenant_id, role=user.role.value)
            return _jsonrpc_error(request_id, -32001, "Unauthorized: MCP access is limited to owner/manager roles")

        # 2.2/2.3: effective capability set = role's granted capabilities
        # intersected with what the token itself is scoped to. A token can
        # only narrow what its user's role already has -- it can never grant
        # more (fixes D2: scopes were written at issuance but never read,
        # so every PAT was full access regardless of what it said).
        role_caps = authz_service.get_capabilities(db, user)
        token_caps = token_service.expand_scopes(db, token_record.scopes)
        effective_caps = role_caps & token_caps

        if method == "tools/list":
            # tools/list filtering is UX, not the security boundary -- the
            # same capability check is re-applied in tools/call below and
            # must never be skipped just because a client already saw a
            # filtered list (plan invariant #1).
            tools_public = [
                {k: v for k, v in t.items() if k != "handler"}
                for t in TOOLS if t.get("capability") in effective_caps
            ]
            return _jsonrpc_result(request_id, {"tools": tools_public})

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            tool = TOOLS_BY_NAME.get(tool_name)
            if not tool:
                return _jsonrpc_error(request_id, -32602, f"Unknown tool: {tool_name}")

            capability = tool.get("capability")
            if capability not in effective_caps:
                log.warning(
                    "mcp_tool_call_denied_capability", tool=tool_name, user_id=user.id,
                    tenant_id=token_record.tenant_id, capability=capability,
                )
                return _jsonrpc_error(request_id, -32001, f"Unauthorized: missing capability for tool '{tool_name}'")

            start = time.monotonic()
            is_error = False

            # 3.6: every write tool requires an explicit confirm:true (a
            # human decision in the loop) plus a client-supplied
            # idempotency_key, deduped for 24h -- a retried tool call (flaky
            # client, timeout-then-retry) must not silently double-move a
            # lead or double-send a draft.
            is_write_tool = not tool.get("annotations", {}).get("readOnlyHint", True)
            block_reason = None
            if is_write_tool:
                if not arguments.get("confirm"):
                    block_reason = "This is a real write action -- call again with confirm: true to proceed."
                elif not arguments.get("idempotency_key"):
                    block_reason = "Write actions require an idempotency_key (any client-generated unique string identifying this specific action)."

            if block_reason:
                is_error = True
                response = {"content": [{"type": "text", "text": block_reason}], "isError": True}
            elif is_write_tool and not cache.idem_check_and_set(
                f"mcp:idem:{token_record.id}:{tool_name}:{arguments['idempotency_key']}"
            ):
                response = {
                    "content": [{"type": "text", "text": "Duplicate call -- this idempotency_key was already processed in the last 24h, no action taken."}],
                    "isError": False,
                }
            else:
                try:
                    result = tool["handler"](db, user, token_record.tenant_id, arguments)
                    if inspect.isawaitable(result):
                        result = await result
                    # 3.1: masking is the default at this boundary for every
                    # tool -- a tool opts OUT via skip_redaction (only
                    # reveal_guest_contact does, since unmasking is its whole
                    # purpose and it's already capability + audit gated).
                    if not tool.get("skip_redaction"):
                        result = redaction.mask_dict(result)
                    response = {
                        "content": [{"type": "text", "text": _to_text(result)}],
                        "isError": False,
                    }
                except ToolError as exc:
                    is_error = True
                    response = {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    }
                except Exception as exc:
                    is_error = True
                    log.error("mcp_tool_call_failed", tool=tool_name, tenant_id=token_record.tenant_id, error=str(exc))
                    response = {
                        "content": [{"type": "text", "text": "Internal error executing tool"}],
                        "isError": True,
                    }
            duration_ms = int((time.monotonic() - start) * 1000)

            # D4: every dispatched tool call gets exactly one audit row,
            # success or error -- this is the only place any MCP action gets
            # written to the hash-chain audit log (reuses the existing
            # writer, no parallel audit path).
            target_type, target_id = _infer_target(arguments)
            append_audit(
                db,
                tenant_id=token_record.tenant_id,
                action=tool.get("audit_action", f"mcp.tool.{tool_name}"),
                actor_user_id=user.id,
                target_type=target_type,
                target_id=target_id,
                payload={
                    "args": _redact_args(arguments),
                    "token_id": token_record.id,
                    "capability": capability,
                    "duration_ms": duration_ms,
                    "is_error": is_error,
                },
            )
            db.commit()

            return _jsonrpc_result(request_id, response)

        return _jsonrpc_error(request_id, -32601, f"Unknown method: {method}")
    finally:
        db.close()


# 2.5: free-text argument keys across the current tool set that can carry
# guest/business PII (search queries, note bodies, stage-change reasons).
# ID-shaped args (inquiry_id, conversation_id, etc.) are opaque UUIDs, not
# PII, and are left as-is so the audit trail stays useful for investigation.
_FREE_TEXT_ARG_KEYS = {"query", "note", "reason"}

# Priority order for inferring an audit event's target from a tool call's
# arguments -- most specific first (a call with both message_id and
# conversation_id is "about" the message, not the whole thread).
_TARGET_ID_PRIORITY = (
    ("message_id", "message"),
    ("inquiry_id", "inquiry"),
    ("conversation_id", "conversation"),
    ("guest_id", "guest"),
)


def _redact_args(args: dict) -> dict:
    redacted = {}
    for key, value in args.items():
        if key in _FREE_TEXT_ARG_KEYS and isinstance(value, str):
            redacted[key] = hashlib.sha256(value.encode()).hexdigest()[:12]
        else:
            redacted[key] = value
    return redacted


def _infer_target(args: dict) -> tuple:
    for key, target_type in _TARGET_ID_PRIORITY:
        if args.get(key):
            return target_type, args[key]
    return None, None


def _to_text(result) -> str:
    import json
    text = json.dumps(result, default=str)
    if len(text) > _MAX_RESULT_CHARS:
        # Chopping mid-structure means this is no longer valid JSON -- that's
        # fine, MCP's text content block is just a string, not a contract to
        # stay parseable. The explicit marker is what matters: the LLM (and
        # anyone debugging) needs to know data is missing, not silently work
        # off a truncated thread/transcript as if it were complete.
        original_len = len(text)
        text = text[:_MAX_RESULT_CHARS]
        text += f'\n\n["truncated": true, "original_chars": {original_len}, "shown_chars": {_MAX_RESULT_CHARS}]'
    return text
