import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import engine, Base
from app.core.logging import configure_logging
from app.core.tenancy import tenant_context_middleware
from app.api.v1.router import api_router
import structlog

configure_logging()
log = structlog.get_logger()

if settings.SENTRY_DSN:
    sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa — registers all models with Base
    Base.metadata.create_all(bind=engine)
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
import structlog as _sl
_sl.get_logger().info("cors_origins_loaded", origins=_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Tenant context: must run after CORS, before route handlers
app.middleware("http")(tenant_context_middleware)

app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0", "env": settings.ENVIRONMENT}
