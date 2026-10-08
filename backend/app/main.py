import asyncio
import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import engine, Base
from app.core.logging import configure_logging
from app.core.tenancy import tenant_context_middleware
from app.core.request_id import request_id_middleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.api.v1.router import api_router
from app.public_api.app import app as public_api_app
import app.services.webhook_events  # noqa: F401  (registers webhook event listeners)
from app.mcp.server import router as mcp_router
from app.mcp.oauth import router as mcp_oauth_router
import structlog

configure_logging()
log = structlog.get_logger()

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        release=settings.SENTRY_RELEASE or None,   # None → Sentry auto-detects from git
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.1,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa — registers all models with Base
    import time
    # Neon serverless wakes on first connection — retry up to 5× with backoff
    for attempt in range(1, 6):
        try:
            Base.metadata.create_all(bind=engine)
            log.info("db_connected", attempt=attempt)
            break
        except Exception as exc:
            log.warning("db_connect_retry", attempt=attempt, error=str(exc))
            if attempt == 5:
                log.error("db_connect_failed_giving_up")
                raise
            time.sleep(attempt * 2)  # 2s, 4s, 6s, 8s
    log.info("haip_api_started", environment=settings.ENVIRONMENT)
    yield
    log.info("haip_api_stopped")


app = FastAPI(
    title="HAIP API",
    description="Hospitality AI Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
)

_origins = settings.allowed_origins_list


class McpCorsBypassMiddleware:
    """/mcp is called by arbitrary external MCP clients (Perisclaw, Claude,
    etc.) authenticated via Bearer token, not cookies -- the dashboard's
    strict origin allowlist below doesn't apply and, if left in place,
    intercepts and rejects /mcp's own preflight (confirmed live: Perisclaw's
    connect-app form failed with a generic error because our own
    CORSMiddleware returned "Disallowed CORS origin" on the preflight).
    Must be registered AFTER the strict CORSMiddleware below (most-recently
    -added add_middleware calls end up OUTERMOST) to actually take effect."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # /oauth/* and /.well-known/* are the MCP connector's OAuth flow
        # (app/mcp/oauth.py) -- called by the same external clients, and by
        # browser-based ones (MCP Inspector) that need the preflight to pass.
        if scope["type"] != "http" or not scope["path"].startswith(("/mcp", "/oauth/", "/.well-known/")):
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        origin = headers.get(b"origin", b"*")

        if scope["method"] == "OPTIONS" and b"access-control-request-method" in headers:
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"access-control-allow-origin", origin),
                    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                    (b"access-control-allow-headers", b"Authorization, Content-Type, Mcp-Protocol-Version, Mcp-Session-Id"),
                    (b"access-control-max-age", b"600"),
                    (b"vary", b"Origin"),
                ],
            })
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"access-control-allow-origin", origin),
                    # Browser clients must be able to read the 401's
                    # WWW-Authenticate header to discover the OAuth flow.
                    (b"access-control-expose-headers", b"WWW-Authenticate, Mcp-Session-Id"),
                ]
            await send(message)

        await self.app(scope, receive, send_wrapper)



# Bug: RateLimitMiddleware used to be add_middleware()'d AFTER CORSMiddleware,
# which (per Starlette's user_middleware.insert(0, ...) — most-recently-added
# ends up OUTERMOST) put it *outside* CORS, not inside as the order comment
# below always claimed. _rate_limit_response() returns a plain Response with
# no CORS headers of its own, so every 429 -- and, worse, every request from
# an origin that was simply rate-limited during a reconnect storm (e.g. many
# tabs retrying at once right after a redeploy) -- came back with no
# Access-Control-Allow-Origin header at all. The browser then refuses to let
# JS read the response, which axios (and any other XHR-based client) reports
# identically to a total network/connectivity failure -- indistinguishable
# from the API actually being down. Registering it first so CORSMiddleware
# (added next) wraps it fixes this: rate-limited responses now carry the same
# CORS headers as everything else.
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "Idempotency-Key"],
    expose_headers=["Content-Length", "X-Request-ID", "Retry-After", "X-RateLimit-Reset"],
)

# Starlette's add_middleware() does user_middleware.insert(0, ...), so the
# MOST RECENTLY registered middleware ends up OUTERMOST (runs first) --
# this must come after CORSMiddleware above to actually intercept /mcp
# preflights before the strict allowlist gets a chance.
app.add_middleware(McpCorsBypassMiddleware)

# Middleware execution order (outermost first):
#   McpCorsBypass → CORS → rate_limit → tenant_context → request_id → routes
app.middleware("http")(request_id_middleware)         # inner
app.middleware("http")(tenant_context_middleware)     # sets tenant_id on request.state

app.include_router(api_router)
app.include_router(mcp_router)
app.include_router(mcp_oauth_router)
# Public, API-key authenticated API with its own OpenAPI file and docs (/api/public/v1/docs)
app.mount("/api/public/v1", public_api_app)


@app.exception_handler(Exception)
async def suppress_sse_disconnect_noise(request: Request, exc: Exception) -> Response:
    """
    Starlette's ServerErrorMiddleware predates Python 3.11 ExceptionGroups.
    When SSE clients disconnect, anyio's TaskGroup cancels both tasks simultaneously
    and raises an ExceptionGroup containing only CancelledError — a normal disconnect,
    not an application error.  Suppress those; re-raise everything else.
    """
    if type(exc).__name__ in ("ExceptionGroup", "BaseExceptionGroup"):
        sub_exceptions = getattr(exc, "exceptions", [])
        if sub_exceptions and all(isinstance(e, asyncio.CancelledError) for e in sub_exceptions):
            return Response(status_code=200)
    raise exc


@app.get("/health")
def health():
    """
    Public health check — used by Railway, load balancers, and uptime monitors.
    Returns 200 as long as the process is alive and DB is reachable.
    Returns 503 only if the database is unreachable (nothing would work anyway).
    """
    from app.core.database import engine
    from sqlalchemy import text
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    status_code = 200 if db_ok else 503
    body = {
        "status": "ok" if db_ok else "degraded",
        "version": "1.0.0",
        "env": settings.ENVIRONMENT,
        "db": "ok" if db_ok else "unreachable",
        # Feature flags — shows operators exactly what's enabled
        "features": {
            "ai":             settings.ai_enabled,
            "transcription":  settings.transcription_enabled,
            "whatsapp":       settings.whatsapp_enabled,
            "email":          settings.email_enabled,
        },
    }
    from fastapi.responses import JSONResponse
    return JSONResponse(content=body, status_code=status_code)
