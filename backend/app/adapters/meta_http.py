"""Meta Graph API: keep access tokens out of URLs, error messages and logs.

httpx puts the full request URL in every HTTPStatusError message, and those messages reach logs and DB rows shown on
screen. So the token goes in the Authorization header, never in `?access_token=`, and `paging.next` URLs (Meta embeds
the token in them) lose their token before we request them. Same pattern as `adapters/instagram/meta_graph.py`.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

# Query parameters that carry a secret. debug_token's input_token stays a query param by Meta's design; callers must
# never log or show that URL.
_SECRET_PARAMS = {"access_token", "input_token", "client_secret", "appsecret_proof"}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def strip_token(url: str) -> str:
    """The URL without any secret query parameter (for a Meta `paging.next` URL before we follow it)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _SECRET_PARAMS]
    return urlunsplit(parts._replace(query=urlencode(query)))


def meta_error(resp: httpx.Response) -> str:
    """Meta's own reason ("(#10) ...", code, subcode) from an error body, without anything secret."""
    try:
        err = (resp.json() or {}).get("error") or {}
    except ValueError:
        return f"HTTP {resp.status_code}"
    parts = [str(err.get("message") or "").strip()]
    if err.get("code") is not None:
        parts.append(f"code {err.get('code')}" + (f"/{err.get('error_subcode')}" if err.get("error_subcode") else ""))
    return " ".join(p for p in parts if p) or f"HTTP {resp.status_code}"


def safe_error(exc: BaseException) -> str:
    """Words for a log line about a failed Meta call: the status or exception class, never str(exc) (it can hold
    the URL)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}: {meta_error(exc.response)}"
    return type(exc).__name__
