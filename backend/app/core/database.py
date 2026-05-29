from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

_is_sqlite = "sqlite" in settings.DATABASE_URL

# pool_pre_ping    — discard stale connections before use (cloud PaaS kills idle conns)
# pool_recycle=280 — return connections after 280s (< 5-min PaaS idle timeout)
# pool_timeout=30  — raise after 30s if no connection available instead of hanging
# connect_args     — SQLite needs check_same_thread=False; Postgres gets connect_timeout
_connect_args: dict = (
    {"check_same_thread": False} if _is_sqlite
    else {"connect_timeout": 10, "keepalives": 1, "keepalives_idle": 30,
          "keepalives_interval": 10, "keepalives_count": 5}
)
_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "pool_size":     5,
    "max_overflow":  10,
    "pool_timeout":  30,
    "connect_args":  _connect_args,
}
if not _is_sqlite:
    # SQLite doesn't support pool_recycle; Postgres/PG needs it
    _engine_kwargs["pool_recycle"] = 280

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    FastAPI dependency that yields a DB session.
    Wraps OperationalError (DB unreachable) in an HTTP 503 so callers get a
    meaningful status code instead of a raw 500.
    """
    from fastapi import HTTPException
    db = SessionLocal()
    try:
        yield db
    except Exception as exc:
        # Re-raise HTTP exceptions as-is; wrap DB connectivity failures as 503
        if isinstance(exc, HTTPException):
            raise
        from sqlalchemy.exc import OperationalError, DatabaseError
        if isinstance(exc, (OperationalError, DatabaseError)):
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable — please retry in a moment",
            ) from exc
        raise
    finally:
        db.close()


def set_tenant_context(db, tenant_id: str):
    """
    Set the Postgres session variable for RLS enforcement.

    Uses a parameterised SELECT set_config() rather than string interpolation
    to eliminate the SQL-injection vector (B7).  The call is silently ignored
    on non-Postgres engines (e.g. SQLite in tests).
    """
    try:
        db.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
    except Exception:
        # Non-Postgres engines (SQLite in unit tests) don't support set_config;
        # skip gracefully — RLS is not enforced in those environments anyway.
        pass
