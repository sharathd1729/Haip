"""GPS adapter registry (Ops phase 3): every tracker feed becomes the same normalised Position.

One provider per business, stored in an Integration row (kind "gps"): `config` = {provider, base_url, ...} in plain JSON,
the secrets (webhook secret, Traccar password/token, the owner's app key) Fernet-encrypted in `credentials_kms_blob` and
never returned by the API. Two shapes:

  push  the provider POSTs to /api/v1/webhooks/gps/{tenant_slug}; `parse_push(provider, body, headers, secret)`
  pull  beat polls every minute; `fetch_positions(provider, config, creds, since)`

| provider | shape | what it is | enabled |
|---|---|---|---|
| webhook | push | HAIP's own JSON format, HMAC-SHA256 signed (adapters/gps/webhook.py has the format) | yes |
| traccar | pull | a Traccar server's REST API; Traccar decodes AIS-140 when the tracker also sends to its IP | yes |
| custom_http | pull | the owner's own GPS app; waits for its API documentation | no, until its API is known |

Adding the owner's app: write adapters/gps/custom_http.py (fetch_positions and/or parse_push returning Position), set
`enabled=True` and its `fields` below. Nothing else changes: ingest, alerts, maps and settings read only this registry.
Every outbound URL is https and passes the SSRF guard (`app.core.url_safety.assert_public_url`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Position:
    """One fix from a tracker. `at` is UTC; speed km/h; heading degrees from north; odometer km (device's own)."""

    device_id: str
    at: datetime
    lat: float
    lng: float
    speed_kmh: float | None = None
    heading: float | None = None
    ignition: bool | None = None
    odometer_km: float | None = None
    provider: str = ""


@dataclass(frozen=True)
class GpsProvider:
    key: str
    label: str
    shape: str  # push | pull
    enabled: bool
    fields: tuple[str, ...] = ()  # connection settings a person types (plain config)
    secret_fields: tuple[str, ...] = ()  # typed secrets, encrypted, never shown again
    blocked_reason: str | None = None


PROVIDERS: dict[str, GpsProvider] = {
    "webhook": GpsProvider(
        key="webhook", label="HAIP webhook (your tracker or app sends positions to HAIP)", shape="push", enabled=True
    ),
    "traccar": GpsProvider(
        key="traccar",
        label="Traccar server",
        shape="pull",
        enabled=True,
        fields=("base_url", "username"),
        secret_fields=("password",),
    ),
    "custom_http": GpsProvider(
        key="custom_http",
        label="Our own GPS app",
        shape="pull",
        enabled=False,
        blocked_reason="Waiting for the GPS app's API details. Use the HAIP webhook meanwhile.",
    ),
}


class GpsProviderBlocked(Exception):
    pass


class GpsAuthError(Exception):
    """A push request that is not signed by this business's secret (or is too old): 401, nothing stored."""


class GpsPayloadError(ValueError):
    """A push or pull answer HAIP cannot read."""


class GpsFetchError(Exception):
    def __init__(self, message: str, *, transient: bool):
        super().__init__(message)
        self.transient = transient


MAX_FUTURE = timedelta(minutes=5)
MAX_AGE = timedelta(days=7)


def usable(p: Position, *, now: datetime) -> bool:
    """A fix worth storing: real coordinates (0,0 = no fix), a sane speed, not from the future or older than a week."""
    return (
        bool(p.device_id)
        and -90 <= p.lat <= 90
        and -180 <= p.lng <= 180
        and not (p.lat == 0 and p.lng == 0)
        and (p.speed_kmh is None or 0 <= p.speed_kmh <= 300)
        and now - MAX_AGE <= p.at <= now + MAX_FUTURE
    )


def get_provider(key: str | None) -> GpsProvider:
    p = PROVIDERS.get(key or "")
    if p is None:
        raise GpsProviderBlocked(f"Unknown GPS provider: {key}")
    if not p.enabled:
        raise GpsProviderBlocked(p.blocked_reason or f"{p.label} is not available.")
    return p


def catalogue() -> list[dict]:
    return [
        {
            "key": p.key,
            "label": p.label,
            "shape": p.shape,
            "enabled": p.enabled,
            "fields": list(p.fields),
            "secret_fields": list(p.secret_fields),
            "blocked_reason": p.blocked_reason,
        }
        for p in PROVIDERS.values()
    ]


def parse_push(provider: GpsProvider, body: bytes, headers: dict, secret: str, *, now: datetime) -> list[Position]:
    """Verify and read a push request. Raises GpsAuthError / GpsPayloadError."""
    if provider.key == "webhook":
        from app.adapters.gps import webhook

        webhook.verify(body, headers, secret, now=now)
        return webhook.parse(body, now=now)
    raise GpsPayloadError(f"{provider.label} does not push to HAIP.")


def fetch_positions(
    provider: GpsProvider, config: dict, creds: dict, since: dict[str, datetime], *, now: datetime
) -> list[Position]:
    """Read new positions from a pull provider. `since` = last fix per external device id. Raises GpsFetchError."""
    if provider.key == "traccar":
        from app.adapters.gps import traccar

        return traccar.fetch_positions(config, creds, since, now=now)
    if provider.key == "custom_http":
        from app.adapters.gps import custom_http

        return custom_http.fetch_positions(config, creds, since, now=now)
    raise GpsFetchError(f"{provider.label} is not polled.", transient=False)
