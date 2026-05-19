"""
Tests for B7: RLS tenant_id SQL injection hardening.

Covers:
- set_tenant_context uses SELECT set_config() (parameterised), NOT string interpolation
- Adversarial tenant_id with SQL metacharacters does not alter the query structure
- set_tenant_context is a no-op (silently skipped) on non-Postgres engines
- tenant_context_middleware no longer opens a DB connection (dead-code removed)
- request.state fields are still set by the middleware
"""

import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy.orm import Session


# ─────────────────────────────────────────────────────────────────
# set_tenant_context
# ─────────────────────────────────────────────────────────────────

class TestSetTenantContext:
    def _call(self, tenant_id: str):
        from app.core.database import set_tenant_context
        db = MagicMock(spec=Session)
        set_tenant_context(db, tenant_id)
        return db

    def test_calls_set_config_with_param(self):
        """Must use a parameterised query, not string interpolation."""
        from sqlalchemy import text
        db = self._call("tenant-abc-123")

        assert db.execute.called
        args, kwargs = db.execute.call_args
        sql_obj = args[0]
        params = args[1] if len(args) > 1 else kwargs.get("params", {})

        # The SQL text must contain set_config — not a raw SET statement
        sql_str = str(sql_obj)
        assert "set_config" in sql_str.lower()
        assert "SET " not in sql_str  # must not use bare SET syntax

    def test_tenant_id_is_bound_not_interpolated(self):
        """The tenant_id value must be passed as a bound parameter."""
        db = self._call("my-tenant-id")

        args, _ = db.execute.call_args
        params = args[1]
        # Bound parameter dict must contain the tenant_id value
        assert params.get("t") == "my-tenant-id"

    def test_adversarial_tenant_id_passed_as_param(self):
        """SQL-injection attempt in tenant_id must be safely bound, not spliced."""
        evil = "'; DROP TABLE tenants; --"
        db = self._call(evil)

        args, _ = db.execute.call_args
        params = args[1]
        # The evil string goes into the param dict untouched — never into the SQL
        assert params.get("t") == evil

    def test_sqlite_silently_skipped(self):
        """
        On non-Postgres engines set_tenant_context must not raise.
        Uses the real SQLite test DB that conftest wires up.
        """
        from app.core.database import set_tenant_context
        from tests.conftest import TestingSessionLocal

        db = TestingSessionLocal()
        try:
            # Should not raise even though SQLite has no set_config()
            set_tenant_context(db, "some-tenant-id")
        finally:
            db.close()

    def test_is_local_flag_set(self):
        """
        The third argument to set_config must be TRUE (is_local) so the
        tenant context is transaction-scoped and cannot leak between requests.
        """
        db = self._call("t-123")
        args, _ = db.execute.call_args
        sql_str = str(args[0]).lower()
        # Postgres is_local = true means the setting is rolled back with the txn
        assert "true" in sql_str


# ─────────────────────────────────────────────────────────────────
# tenant_context_middleware — no longer touches the DB
# ─────────────────────────────────────────────────────────────────

class TestTenantContextMiddleware:
    """
    Verify the middleware populates request.state but never opens a DB session.
    """

    def _make_request(self, token: str | None = None):
        from starlette.requests import Request
        headers = []
        if token:
            headers.append((b"authorization", f"Bearer {token}".encode()))
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/conversations",
            "headers": headers,
            "query_string": b"",
        }
        return Request(scope)

    def _make_token(self, tenant_id="t1", user_id="u1", role="owner"):
        from app.core.security import create_access_token
        return create_access_token({"sub": user_id, "tenant_id": tenant_id, "role": role})

    def test_middleware_does_not_import_session_local(self):
        """
        After B7: tenancy.py must not import SessionLocal at all —
        the dead-code DB session has been removed.
        """
        import app.core.tenancy as tenancy_module
        assert not hasattr(tenancy_module, "SessionLocal"), (
            "tenancy.py should not import SessionLocal — "
            "the middleware no longer opens a DB connection"
        )

    @pytest.mark.anyio
    async def test_middleware_sets_request_state(self):
        from app.core.tenancy import tenant_context_middleware

        token = self._make_token(tenant_id="t-xyz", user_id="u-abc", role="manager")
        request = self._make_request(token)

        async def _next(req):
            from starlette.responses import Response
            return Response("ok")

        await tenant_context_middleware(request, _next)

        assert request.state.tenant_id == "t-xyz"
        assert request.state.user_id == "u-abc"
        assert request.state.role == "manager"

    @pytest.mark.anyio
    async def test_public_path_skips_middleware(self):
        """Health check and auth routes must not require a token."""
        from app.core.tenancy import tenant_context_middleware
        from starlette.requests import Request

        scope = {
            "type": "http", "method": "GET",
            "path": "/health", "headers": [], "query_string": b"",
        }
        request = Request(scope)

        called = []

        async def _next(req):
            called.append(True)
            from starlette.responses import Response
            return Response("ok")

        await tenant_context_middleware(request, _next)
        assert called  # call_next was reached without error

    @pytest.mark.anyio
    async def test_no_auth_header_passes_through(self):
        from app.core.tenancy import tenant_context_middleware

        request = self._make_request(token=None)
        called = []

        async def _next(req):
            called.append(True)
            from starlette.responses import Response
            return Response("ok")

        await tenant_context_middleware(request, _next)
        assert called
