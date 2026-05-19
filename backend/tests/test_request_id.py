"""
Tests for B16: Request-ID propagation.

Covers:
- _generate_request_id produces 26-char hex string
- _generate_request_id values are lexicographically ascending over time
- Middleware generates X-Request-ID when header absent
- Middleware echoes incoming X-Request-ID when present and valid
- Incoming ID too long → ignored, fresh ID generated
- X-Request-ID present in every response
- Response X-Request-ID matches echoed or generated value
- get_request_id() returns empty string outside a request context
- structlog context-vars are bound (request_id present in log output)
- Middleware registers on the app (end-to-end via TestClient)
"""

import time
import pytest
from unittest.mock import patch
from starlette.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_id import (
    _generate_request_id,
    get_request_id,
    REQUEST_ID_HEADER,
    _MAX_INCOMING_ID_LEN,
    _request_id_ctx_var,
)


# ─────────────────────────────────────────────────────────────────
# _generate_request_id unit tests
# ─────────────────────────────────────────────────────────────────

def test_generate_returns_26_chars():
    rid = _generate_request_id()
    assert len(rid) == 26, f"Expected 26 chars, got {len(rid)}: {rid!r}"


def test_generate_is_hex():
    rid = _generate_request_id()
    assert all(c in "0123456789abcdef" for c in rid), f"Non-hex chars in {rid!r}"


def test_generate_ids_are_unique():
    ids = {_generate_request_id() for _ in range(20)}
    assert len(ids) == 20


def test_generate_ids_are_sortable_by_time():
    """Lexicographic order must match temporal order (within test run)."""
    id1 = _generate_request_id()
    time.sleep(0.002)   # 2 ms gap — timestamp prefix shifts
    id2 = _generate_request_id()
    assert id1 < id2, f"Expected {id1!r} < {id2!r}"


# ─────────────────────────────────────────────────────────────────
# get_request_id outside a request
# ─────────────────────────────────────────────────────────────────

def test_get_request_id_outside_request_returns_empty():
    # Reset ctx var to its default
    token = _request_id_ctx_var.set("")
    try:
        assert get_request_id() == ""
    finally:
        _request_id_ctx_var.reset(token)


# ─────────────────────────────────────────────────────────────────
# request_id_middleware unit tests
# ─────────────────────────────────────────────────────────────────

async def _dummy_next(request: Request) -> Response:
    return Response("ok", status_code=200)


def _make_request(headers: dict | None = None):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "query_string": b"",
    }
    return Request(scope)


class TestRequestIdMiddleware:
    @pytest.mark.anyio
    async def test_generates_id_when_header_absent(self):
        from app.core.request_id import request_id_middleware
        request = _make_request()
        response = await request_id_middleware(request, _dummy_next)
        rid = response.headers.get(REQUEST_ID_HEADER)
        assert rid is not None
        assert len(rid) == 26

    @pytest.mark.anyio
    async def test_echoes_valid_incoming_id(self):
        from app.core.request_id import request_id_middleware
        incoming = "abc123def456"
        request = _make_request({REQUEST_ID_HEADER: incoming})
        response = await request_id_middleware(request, _dummy_next)
        assert response.headers.get(REQUEST_ID_HEADER) == incoming

    @pytest.mark.anyio
    async def test_ignores_too_long_incoming_id(self):
        from app.core.request_id import request_id_middleware
        long_id = "x" * (_MAX_INCOMING_ID_LEN + 1)
        request = _make_request({REQUEST_ID_HEADER: long_id})
        response = await request_id_middleware(request, _dummy_next)
        rid = response.headers.get(REQUEST_ID_HEADER)
        # Should be a freshly generated ID, not the oversized one
        assert rid != long_id
        assert len(rid) == 26

    @pytest.mark.anyio
    async def test_context_var_set_during_request(self):
        from app.core.request_id import request_id_middleware, get_request_id

        captured = []

        async def _capturing_next(req):
            captured.append(get_request_id())
            return Response("ok")

        request = _make_request()
        await request_id_middleware(request, _capturing_next)

        assert len(captured) == 1
        assert len(captured[0]) == 26  # was set inside the request

    @pytest.mark.anyio
    async def test_context_var_reset_after_request(self):
        from app.core.request_id import request_id_middleware, get_request_id

        request = _make_request()
        await request_id_middleware(request, _dummy_next)

        # After the request the ctx var should be back to ""
        assert get_request_id() == ""

    @pytest.mark.anyio
    async def test_structlog_contextvars_bound(self):
        """request_id should appear in structlog's context-var store during request."""
        import structlog
        from app.core.request_id import request_id_middleware

        bound_keys = []

        async def _check_ctx(req):
            ctx = structlog.contextvars.get_contextvars()
            bound_keys.extend(ctx.keys())
            return Response("ok")

        request = _make_request()
        await request_id_middleware(request, _check_ctx)

        assert "request_id" in bound_keys


# ─────────────────────────────────────────────────────────────────
# End-to-end via TestClient
# ─────────────────────────────────────────────────────────────────

class TestRequestIdEndToEnd:
    def test_health_response_has_x_request_id(self, client):
        response = client.get("/health")
        assert REQUEST_ID_HEADER in response.headers

    def test_provided_request_id_echoed(self, client):
        my_id = "test-request-id-12345"
        response = client.get("/health", headers={REQUEST_ID_HEADER: my_id})
        assert response.headers.get(REQUEST_ID_HEADER) == my_id

    def test_consecutive_requests_get_different_ids(self, client):
        r1 = client.get("/health")
        r2 = client.get("/health")
        id1 = r1.headers.get(REQUEST_ID_HEADER)
        id2 = r2.headers.get(REQUEST_ID_HEADER)
        assert id1 != id2
