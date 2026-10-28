"""Traccar REST API (pull). Route B of the plan: the AIS-140 tracker also sends to a Traccar server, which decodes it.

config {base_url: "https://traccar.example.com", username} + secret {password}. With no username the password is sent as a
Bearer token (Traccar 5.x API tokens). Calls: GET /api/devices (id -> uniqueId = IMEI, our device id), then per device
GET /api/positions?deviceId=&from=&to= for the fixes since the last one HAIP has (at most the last hour).
Traccar speed is in knots and odometer/totalDistance in metres; both are converted here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.adapters.gps import GpsFetchError, Position, usable
from app.core.url_safety import UnsafeURLError, assert_public_url

TIMEOUT = 15.0
LOOKBACK = timedelta(hours=1)
KNOT_KMH = 1.852


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _time(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(UTC)


def parse_position(row: dict, unique_id: str) -> Position:
    attrs = row.get("attributes") or {}
    odo_m = attrs.get("odometer")
    if odo_m is None:
        odo_m = attrs.get("totalDistance")
    ign = attrs.get("ignition")
    speed = row.get("speed")
    return Position(
        device_id=unique_id,
        at=_time(row.get("fixTime") or row.get("deviceTime")),
        lat=float(row["latitude"]),
        lng=float(row["longitude"]),
        speed_kmh=round(float(speed) * KNOT_KMH, 1) if speed is not None else None,
        heading=float(row["course"]) if row.get("course") is not None else None,
        ignition=ign if isinstance(ign, bool) else None,
        odometer_km=round(float(odo_m) / 1000, 1) if odo_m is not None else None,
        provider="traccar",
    )


def _get(client: httpx.Client, url: str, params: dict | None = None) -> list:
    try:
        r = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise GpsFetchError(f"Traccar did not answer: {type(exc).__name__}", transient=True) from exc
    if r.status_code in (401, 403):
        raise GpsFetchError("Traccar refused the username or password.", transient=False)
    if r.status_code >= 300:
        raise GpsFetchError(f"Traccar answered {r.status_code}.", transient=r.status_code >= 429)
    data = r.json()
    if not isinstance(data, list):
        raise GpsFetchError("Traccar answered something that is not a list.", transient=False)
    return data


def fetch_positions(config: dict, creds: dict, since: dict[str, datetime], *, now: datetime) -> list[Position]:
    base = (config.get("base_url") or "").rstrip("/")
    try:
        assert_public_url(base, allow_http=False)
    except UnsafeURLError as exc:
        raise GpsFetchError(str(exc), transient=False) from exc
    user, password = config.get("username") or "", creds.get("password") or ""
    auth = (user, password) if user else None
    headers = {"Accept": "application/json", **({} if user else {"Authorization": f"Bearer {password}"})}
    out: list[Position] = []
    # follow_redirects=False: a redirect could point the server at an internal address the guard never checked.
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False, auth=auth, headers=headers) as client:
        for dev in _get(client, f"{base}/api/devices"):
            uid = str(dev.get("uniqueId") or "").strip()[:64]
            if not uid or dev.get("disabled"):
                continue
            start = max(since.get(uid) or now - LOOKBACK, now - LOOKBACK)
            for row in _get(
                client, f"{base}/api/positions", {"deviceId": dev["id"], "from": _iso(start), "to": _iso(now)}
            ):
                try:
                    p = parse_position(row, uid)
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
                if row.get("valid", True) and usable(p, now=now) and p.at > start:
                    out.append(p)
    return out
