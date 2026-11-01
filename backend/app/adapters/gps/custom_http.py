"""The owner's own GPS tracking app: a slot, not a client yet (disabled in the registry).

When its API documentation arrives, replace fetch_positions below (or add parse_push for a push API) so it returns
app.adapters.gps.Position rows, list its connection settings in PROVIDERS["custom_http"].fields / secret_fields and set
enabled=True. Rules every adapter keeps: https only and `assert_public_url` before any request, no redirects followed,
times in UTC, speed in km/h, odometer in km, `usable()` on every fix, GpsFetchError(transient=...) on failure. Ingest,
alerts, the map and the settings page need no change.
"""

from __future__ import annotations

from datetime import datetime

from app.adapters.gps import GpsFetchError, Position


def fetch_positions(config: dict, creds: dict, since: dict[str, datetime], *, now: datetime) -> list[Position]:
    raise GpsFetchError("The GPS app's API is not connected yet.", transient=False)
