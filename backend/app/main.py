import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import engine, Base
from app.core.logging import configure_logging
from app.core.tenancy import tenant_context_middleware
from app.core.request_id import request_id_middleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.api.v1.router import api_router
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Middleware execution order (last-registered runs first for requests):
#   CORS → rate_limit → tenant_context → request_id → route handlers
# Starlette registers middleware as a stack — add in reverse desired order.
app.middleware("http")(request_id_middleware)         # inner
app.middleware("http")(tenant_context_middleware)     # sets tenant_id on request.state
app.add_middleware(RateLimitMiddleware)               # outermost: rate limit after CORS

app.include_router(api_router)


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
