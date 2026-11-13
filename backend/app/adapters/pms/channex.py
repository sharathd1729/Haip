"""Channex.io channel manager adapter (docs.channex.io, API v1). Synchronous httpx: it runs inside Celery tasks.

Auth: header `user-api-key` (an API key the owner creates in their Channex user profile), stored encrypted on the
tenant's Integration row (kind "channex"). The base URL is per connection (`config["base_url"]`): staging
(https://staging.channex.io/api/v1) until the property passes Channex's certification, then the production host they
give. HAIP never hard-codes production.

What HAIP uses:
  push   POST /availability   {"values": [{property_id, room_type_id, date_from, date_to, availability}]}
         POST /restrictions   {"values": [{property_id, rate_plan_id, date_from, date_to, rate, min_stay_arrival, ...}]}
         Both answer 200 even when some values are rejected: `meta.warnings` lists them (returned to the caller).
  pull   GET  /booking_revisions/feed      unacknowledged revisions (status new | modified | cancelled)
         POST /booking_revisions/{id}/ack  after HAIP has stored it (an acked revision leaves the feed; guest contact
                                           details are removed from Channex after ack, so store them first)
  map    GET  /properties, /room_types, /rate_plans (filter[property_id]) for the mapping screen
"""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger()

STAGING = "https://staging.channex.io/api/v1"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_VALUES = 500  # values per ARI request: Channex takes batches; keep each request small enough to retry cheaply


class ChannexError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ChannexClient:
    def __init__(self, api_key: str, base_url: str | None = None, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise ChannexError("Channex API key is missing")
        base = (base_url or STAGING).rstrip("/")
        if not base.startswith("https://") or "channex.io" not in base.split("/")[2]:
            raise ChannexError("Channex base URL must be an https channex.io address")  # SSRF guard: only Channex hosts
        self._base = base
        self._http = httpx.Client(timeout=TIMEOUT, headers={"user-api-key": api_key, "Content-Type": "application/json"},
                                  follow_redirects=False, transport=transport)

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            resp = self._http.request(method, f"{self._base}{path}", **kw)
        except httpx.HTTPError as exc:
            raise ChannexError(f"Channex unreachable: {type(exc).__name__}") from exc
        if resp.status_code == 401:
            raise ChannexError("Channex refused the API key", 401)
        if resp.status_code == 429:
            raise ChannexError("Channex rate limit reached; will retry", 429)
        if resp.status_code >= 400:
            raise ChannexError(f"Channex answered HTTP {resp.status_code}", resp.status_code)
        try:
            return resp.json() if resp.content else {}
        except ValueError as exc:
            raise ChannexError("Channex sent a reply that is not JSON") from exc

    # ── ARI push ──────────────────────────────────────────────────────────────
    def _push(self, path: str, values: list[dict]) -> list:
        warnings: list = []
        for i in range(0, len(values), MAX_VALUES):
            out = self._call("POST", path, json={"values": values[i:i + MAX_VALUES]})
            warnings += (out.get("meta") or {}).get("warnings") or []
        return warnings

    def push_availability(self, values: list[dict]) -> list:
        return self._push("/availability", values) if values else []

    def push_restrictions(self, values: list[dict]) -> list:
        return self._push("/restrictions", values) if values else []

    # ── Bookings ──────────────────────────────────────────────────────────────
    def booking_feed(self) -> list[dict]:
        """Unacknowledged booking revisions, each flattened to its `attributes` (+ `id`)."""
        out = self._call("GET", "/booking_revisions/feed")
        rows = out.get("data") or []
        return [{**(r.get("attributes") or {}), "id": r.get("id") or (r.get("attributes") or {}).get("id")} for r in rows]

    def ack(self, revision_id: str) -> None:
        self._call("POST", f"/booking_revisions/{revision_id}/ack")

    # ── Mapping lists ─────────────────────────────────────────────────────────
    def _list(self, path: str, property_id: str | None = None) -> list[dict]:
        params = {"filter[property_id]": property_id} if property_id else None
        out = self._call("GET", path, params=params)
        return [{"id": r.get("id"), **(r.get("attributes") or {})} for r in out.get("data") or []]

    def properties(self) -> list[dict]:
        return self._list("/properties")

    def room_types(self, property_id: str) -> list[dict]:
        return self._list("/room_types", property_id)

    def rate_plans(self, property_id: str) -> list[dict]:
        return self._list("/rate_plans", property_id)
