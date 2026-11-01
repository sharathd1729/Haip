"""HAIP's own GPS push format. Any tracker server or app can send positions to HAIP this way.

    POST https://<api host>/api/v1/webhooks/gps/<business slug>
    Content-Type: application/json
    X-HAIP-Timestamp: 1793182500                 (unix seconds, when you send)
    X-HAIP-Signature: sha256=<hex>               HMAC-SHA256(secret, "<timestamp>.<raw body>")

    {"positions": [
      {"device_id": "861234567890123",           tracker IMEI or your own id for the vehicle's tracker (required)
       "time": "2026-10-28T10:15:00Z",           when the fix was taken, ISO 8601 with a zone, or unix seconds (required)
       "lat": 12.9716, "lng": 77.5946,           decimal degrees (required)
       "speed_kmh": 54.2,                        optional
       "heading": 180,                           optional, degrees from north
       "ignition": true,                         optional
       "odometer_km": 87412.5}                   optional, the vehicle's own odometer
    ]}

Up to 500 positions per request, body up to 512 KB. A request older or newer than 5 minutes is refused (replays). Sending
the same device + time twice is harmless: it is stored once. Unknown device ids appear on the GPS settings page so a
manager can map them to a vehicle; their positions are not kept until then.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta

from app.adapters.gps import GpsAuthError, GpsPayloadError, Position, usable

WINDOW = timedelta(minutes=5)
MAX_POSITIONS = 500
MAX_BODY = 512 * 1024


def _header(headers: dict, name: str) -> str:
    for k, v in headers.items():
        if k.lower() == name:
            return v or ""
    return ""


def sign(body: bytes, secret: str, timestamp: int) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def verify(body: bytes, headers: dict, secret: str, *, now: datetime) -> None:
    if not secret:
        raise GpsAuthError("No webhook secret is set for this business.")
    raw_ts = _header(headers, "x-haip-timestamp")
    try:
        ts = int(raw_ts)
    except ValueError as exc:
        raise GpsAuthError("Missing or bad X-HAIP-Timestamp.") from exc
    if abs(now - datetime.fromtimestamp(ts, UTC)) > WINDOW:
        raise GpsAuthError("Request is older or newer than 5 minutes.")
    if not secrets.compare_digest(sign(body, secret, ts), _header(headers, "x-haip-signature")):
        raise GpsAuthError("Signature does not match.")


def _time(v) -> datetime:
    if isinstance(v, bool):
        raise ValueError("time")
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, UTC)
    at = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise ValueError("time needs a zone")
    return at.astimezone(UTC)


def _num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError("number")
    return float(v)


def parse(body: bytes, *, now: datetime) -> list[Position]:
    """Read a verified body. Bad rows are skipped (one bad fix never drops the batch); a bad body raises."""
    if len(body) > MAX_BODY:
        raise GpsPayloadError("Body is larger than 512 KB.")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise GpsPayloadError("Body is not JSON.") from exc
    rows = data.get("positions") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise GpsPayloadError('Body needs a "positions" list.')
    if len(rows) > MAX_POSITIONS:
        raise GpsPayloadError("At most 500 positions per request.")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            ign = r.get("ignition")
            p = Position(
                device_id=str(r.get("device_id") or "").strip()[:64],
                at=_time(r["time"]),
                lat=float(r["lat"]),
                lng=float(r["lng"]),
                speed_kmh=_num(r.get("speed_kmh")),
                heading=_num(r.get("heading")),
                ignition=ign if isinstance(ign, bool) else None,
                odometer_km=_num(r.get("odometer_km")),
                provider="webhook",
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if usable(p, now=now):
            out.append(p)
    return out
