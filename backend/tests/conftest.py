"""
Shared pytest fixtures for all HAIP backend tests.

Uses an in-memory SQLite DB (overriding DATABASE_URL) so tests run
without a real Postgres instance during local development.
For CI, DATABASE_URL is set to the testcontainer Postgres service.
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Override DB before app import
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-placeholder")
os.environ.setdefault("DEEPGRAM_API_KEY", "placeholder")
# Integration credentials are Fernet-encrypted. Several test modules need a key; without a default
# they only passed when an earlier module happened to set one, so results depended on test order.
from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.database import Base, get_db  # noqa: E402
from app.main import app                     # noqa: E402

TEST_DB_URL = os.environ.get("DATABASE_URL", "sqlite:///./test.db")
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False} if "sqlite" in TEST_DB_URL else {})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create all tables once per session."""
    Base.metadata.create_all(bind=engine)
    yield
    # Only the throwaway SQLite file is dropped. On PostgreSQL (CI, or a local test container) the
    # database was built by ``alembic upgrade head``, whose tables have foreign keys the models do not
    # declare, so ``drop_all`` fails with DependentObjectsStillExist and errored the whole session.
    # It would also wipe whatever database DATABASE_URL pointed at; the test database is discarded instead.
    if engine.dialect.name == "sqlite":
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    """Per-test DB session, rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    # On PostgreSQL the session must use SAVEPOINTs inside the per-test transaction. In the default join mode a
    # Session.close() or rollback() by the code under test (every Celery task closes its session) rolls back the
    # whole outer transaction, so rows the test had committed through this session vanish and the test fails with
    # "Instance ... has been deleted, or its row is otherwise not present". SQLite hides this because pysqlite
    # only begins a transaction on the first write; its savepoint support is unreliable, so it keeps the default.
    mode = {"join_transaction_mode": "create_savepoint"} if engine.dialect.name == "postgresql" else {}
    session = TestingSessionLocal(bind=connection, **mode)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db):
    """FastAPI test client with DB dependency overridden."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def tenant_and_user(db):
    """Create a test tenant + owner user, return (tenant, user, tokens)."""
    import uuid, hashlib
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.core.security import create_access_token, create_refresh_token, get_password_hash

    tenant = Tenant(id=str(uuid.uuid4()), name="Test Tenant", slug=f"test-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()

    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name="Test Owner",
        email=f"owner-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("testpassword123"),
        role=UserRole.OWNER,
        is_active=True,
    )
    db.add(user)
    db.commit()

    payload = {"sub": user.id, "tenant_id": tenant.id, "role": user.role.value}
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)

    # Persist the RefreshToken DB row -- /auth/refresh and /auth/logout look
    # tokens up by hash in the DB, not just by decoding the JWT. Without this
    # row, every refresh/logout test 401s with "not found" regardless of the
    # endpoint's actual logic (this was previously missing, silently making
    # test_refresh_token and test_logout vacuous).
    from app.models.user import RefreshToken
    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        tenant_id=tenant.id,
        token_hash=hashlib.sha256(refresh_token.encode()).hexdigest(),
    ))
    db.commit()

    return {"tenant": tenant, "user": user, "access_token": access_token, "refresh_token": refresh_token}
