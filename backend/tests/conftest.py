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
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    """Per-test DB session, rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
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

    return {"tenant": tenant, "user": user, "access_token": access_token, "refresh_token": refresh_token}
