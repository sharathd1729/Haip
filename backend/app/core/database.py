from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
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
