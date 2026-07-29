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
from fastapi import APIRouter, Request, Response
import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.models.user import User
from app.services import token_service
from app.mcp.tools import TOOLS, TOOLS_BY_NAME, ToolError

log = structlog.get_logger()
router = APIRouter(prefix="/mcp", tags=["mcp"])

_PROTOCOL_VERSION = "2024-11-05"


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
        user = db.query(User).filter_by(id=token_record.user_id, tenant_id=token_record.tenant_id).first()
        if not user:
            return _jsonrpc_error(request_id, -32001, "Unauthorized: token's user no longer exists")

        if method == "tools/list":
            tools_public = [
                {k: v for k, v in t.items() if k != "handler"} for t in TOOLS
            ]
            return _jsonrpc_result(request_id, {"tools": tools_public})

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            tool = TOOLS_BY_NAME.get(tool_name)
            if not tool:
                return _jsonrpc_error(request_id, -32602, f"Unknown tool: {tool_name}")
            try:
                result = tool["handler"](db, user, token_record.tenant_id, arguments)
                return _jsonrpc_result(request_id, {
                    "content": [{"type": "text", "text": _to_text(result)}],
                    "isError": False,
                })
            except ToolError as exc:
                return _jsonrpc_result(request_id, {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                })
            except Exception as exc:
                log.error("mcp_tool_call_failed", tool=tool_name, tenant_id=token_record.tenant_id, error=str(exc))
                return _jsonrpc_result(request_id, {
                    "content": [{"type": "text", "text": "Internal error executing tool"}],
                    "isError": True,
                })

        return _jsonrpc_error(request_id, -32601, f"Unknown method: {method}")
    finally:
        db.close()


def _to_text(result) -> str:
    import json
    return json.dumps(result, default=str)
