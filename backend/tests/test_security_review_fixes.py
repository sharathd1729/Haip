"""Regression tests for the Sep 2026 security review:
1. Instagram OAuth callback reflected XSS (same-origin as the app).
2. Gemini API key in the request URL (leaked into logs via error messages).
3. SSRF through tenant-supplied URLs (knowledge import, RentalWise base URL).
"""
import socket
from unittest.mock import MagicMock, patch

import pytest

from app.core import url_safety
from app.core.url_safety import UnsafeURLError, assert_public_url, safe_get


def _resolves_to(ip):
    return lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


# ── 1. XSS ────────────────────────────────────────────────────────────────────

def test_instagram_callback_escapes_error_param(client):
    payload = "<script>fetch('/api/auth/session')</script>"
    resp = client.get("/api/v1/integrations/instagram/oauth-callback", params={"error": payload})
    assert resp.status_code == 400
    assert "<script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


# ── 2. Gemini key never in the URL ────────────────────────────────────────────

def test_gemini_key_sent_as_header_not_url():
    from app.adapters.llm import gemini
    with patch.object(gemini.settings, "GEMINI_API_KEY", "secret-key-123"):
        assert "secret-key-123" not in gemini._build_url("gemini-x")
        assert gemini._auth_headers() == {"x-goog-api-key": "secret-key-123"}


# ── 3. SSRF ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ip", ["169.254.169.254", "127.0.0.1", "10.0.0.5", "172.17.0.2", "192.168.1.1", "0.0.0.0", "::1"])
def test_private_addresses_are_refused(ip):
    with patch.object(url_safety.socket, "getaddrinfo", _resolves_to(ip)):
        with pytest.raises(UnsafeURLError):
            assert_public_url("http://example.com/page")


def test_public_address_is_allowed():
    with patch.object(url_safety.socket, "getaddrinfo", _resolves_to("93.184.216.34")):
        assert_public_url("https://example.com/faq")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x"])
def test_non_http_schemes_refused(url):
    with pytest.raises(UnsafeURLError):
        assert_public_url(url)


def test_redirect_to_internal_address_is_refused():
    """A public page that 302s to the metadata service must not be followed."""
    def fake_resolve(host, port, *a, **k):
        ip = "169.254.169.254" if host == "169.254.169.254" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    redirect = MagicMock(status_code=302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    fake_client = MagicMock()
    fake_client.__enter__.return_value.get.return_value = redirect
    with patch.object(url_safety.socket, "getaddrinfo", fake_resolve), \
         patch.object(url_safety.httpx, "Client", return_value=fake_client):
        with pytest.raises(UnsafeURLError):
            safe_get("https://evil.example/r", timeout=5)
    # Only the first (public) hop was requested.
    assert fake_client.__enter__.return_value.get.call_count == 1


def test_knowledge_import_refuses_internal_url():
    from app.services import knowledge_ingest
    with patch.object(url_safety.socket, "getaddrinfo", _resolves_to("127.0.0.1")):
        with pytest.raises(knowledge_ingest.IngestError):
            knowledge_ingest.fetch_url_text("http://localhost:8000/docs")


def test_rentalwise_base_url_must_be_public():
    from app.adapters.pms.retalwise import RentalwiseAdapter
    # Own domain: allowed without a DNS lookup.
    RentalwiseAdapter(api_token="t", base_url="https://partners-api.rentalwise.com")
    with patch.object(url_safety.socket, "getaddrinfo", _resolves_to("10.0.0.7")):
        with pytest.raises(UnsafeURLError):
            RentalwiseAdapter(api_token="t", base_url="https://internal.example")
    with pytest.raises(UnsafeURLError):
        RentalwiseAdapter(api_token="t", base_url="http://app.rentalwise.io")  # https only
