"""Outbound webhooks: endpoints, signing, delivery with retries.

Signature (documented for customers): the request carries
    X-HAIP-Timestamp: <unix seconds>
    X-HAIP-Signature: v1=<hex HMAC-SHA256 of "<timestamp>.<raw body>" with the endpoint secret>
so a receiver can verify the sender and reject replays.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.database import set_tenant_context
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.core.url_safety import UnsafeURLError, assert_public_url
from app.models.webhook import WebhookDelivery, WebhookEndpoint

log = structlog.get_logger()

SECRET_PREFIX = "whsec_"
TIMEOUT_SECONDS = 10
# Wait before retry N (after the Nth failed attempt). Total span of about 22 hours.
BACKOFF = [timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=10), timedelta(minutes=30),
           timedelta(hours=1), timedelta(hours=3), timedelta(hours=6), timedelta(hours=12)]
MAX_ATTEMPTS = len(BACKOFF) + 1
DISABLE_AFTER_FAILURES = 100            # consecutive failed attempts before an endpoint is switched off

EVENTS: dict[str, str] = {
    "booking.created": "A booking was created (in HAIP, by a sold lead, or through the API)",
    "booking.updated": "A booking changed: dates, guests, add-ons, payments, schedule, notes or requests",
    "booking.cancelled": "A booking was cancelled",
    "payment.received": "A payment was recorded on a booking (including online payments)",
    "message.received": "A guest sent a WhatsApp or Instagram message",
    "message.status": "An outbound message changed state: sent, delivered, read or failed",
}


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"v1={mac}"


def endpoint_secret(ep: WebhookEndpoint) -> str:
    blob = bytes(ep.secret_enc) if isinstance(ep.secret_enc, memoryview) else ep.secret_enc
    return decrypt_credentials(blob).get("secret", "")


def create_endpoint(db: Session, tenant_id: str, url: str, events: list[str], description: Optional[str],
                    created_by: Optional[str]) -> tuple[WebhookEndpoint, str]:
    secret = new_secret()
    ep = WebhookEndpoint(tenant_id=tenant_id, url=url, description=description, events=sorted(set(events)),
                         secret_enc=encrypt_credentials({"secret": secret}), is_active=True, created_by=created_by)
    db.add(ep)
    db.flush()
    return ep, secret


def envelope(event_type: str, data: dict, event_id: Optional[str] = None) -> dict:
    return {"id": event_id or f"evt_{uuid.uuid4().hex[:24]}", "type": event_type,
            "created_at": datetime.now(timezone.utc).isoformat(), "data": data}


def queue_event(db: Session, tenant_id: str, event_type: str, data: dict,
                only_endpoint: Optional[str] = None) -> list[str]:
    """Write one delivery row per active endpoint subscribed to this event, in the caller's
    transaction. Returns the delivery ids; the caller dispatches them after commit."""
    q = db.query(WebhookEndpoint).filter(WebhookEndpoint.tenant_id == tenant_id, WebhookEndpoint.is_active.is_(True))
    if only_endpoint:
        q = q.filter(WebhookEndpoint.id == only_endpoint)
    env = envelope(event_type, data)
    ids: list[str] = []
    now = datetime.now(timezone.utc)
    for ep in q.all():
        if event_type != "ping" and event_type not in (ep.events or []):
            continue
        d = WebhookDelivery(tenant_id=tenant_id, endpoint_id=ep.id, event_id=env["id"], event_type=event_type,
                            payload=env, status="pending", attempts=0, next_attempt_at=now)
        db.add(d)
        db.flush()
        ids.append(d.id)
    return ids


def _fail(db: Session, d: WebhookDelivery, ep: WebhookEndpoint, error: str, response_status: Optional[int], permanent: bool = False):
    now = datetime.now(timezone.utc)
    d.attempts += 1
    d.response_status, d.last_error = response_status, error[:500]
    ep.consecutive_failures = (ep.consecutive_failures or 0) + 1
    ep.last_failure_at = now
    if permanent or d.attempts >= MAX_ATTEMPTS:
        d.status, d.next_attempt_at = "failed", None
    else:
        d.status, d.next_attempt_at = "pending", now + BACKOFF[d.attempts - 1]
    if ep.is_active and ep.consecutive_failures >= DISABLE_AFTER_FAILURES:
        ep.is_active, ep.disabled_reason = False, f"Switched off after {DISABLE_AFTER_FAILURES} failed deliveries in a row. Fix your endpoint and enable it again."
        log.warning("webhook_endpoint_disabled", endpoint_id=ep.id, tenant_id=ep.tenant_id)


def deliver(db: Session, delivery_id: str, tenant_id: str, client: Optional[httpx.Client] = None) -> str:
    """Send one delivery now. Returns its status afterwards. Never raises for a customer-side
    problem: the outcome is recorded on the row and the retry schedule decides what happens next."""
    set_tenant_context(db, tenant_id)
    d = db.query(WebhookDelivery).filter_by(id=delivery_id, tenant_id=tenant_id).first()
    if d is None or d.status != "pending":
        return d.status if d else "missing"
    ep = db.query(WebhookEndpoint).filter_by(id=d.endpoint_id, tenant_id=tenant_id).first()
    if ep is None or not ep.is_active:
        d.status, d.last_error, d.next_attempt_at = "failed", "Endpoint is switched off or was deleted.", None
        db.commit()
        return d.status

    body = json.dumps(d.payload, separators=(",", ":"), sort_keys=True).encode()
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json", "User-Agent": "HAIP-Webhooks/1.0",
        "X-HAIP-Event": d.event_type, "X-HAIP-Delivery": d.id, "X-HAIP-Timestamp": str(ts),
        "X-HAIP-Signature": sign(endpoint_secret(ep), ts, body),
    }
    try:
        assert_public_url(ep.url)
    except UnsafeURLError as exc:
        _fail(db, d, ep, f"Blocked: {exc}", None, permanent=True)
        db.commit()
        return d.status

    try:
        own = client is None
        client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
        try:
            resp = client.post(ep.url, content=body, headers=headers)
        finally:
            if own:
                client.close()
    except httpx.HTTPError as exc:
        _fail(db, d, ep, f"Could not reach your server: {exc.__class__.__name__}", None)
        db.commit()
        return d.status

    now = datetime.now(timezone.utc)
    if 200 <= resp.status_code < 300:
        d.status, d.attempts, d.response_status, d.last_error = "success", d.attempts + 1, resp.status_code, None
        d.delivered_at, d.next_attempt_at = now, None
        ep.consecutive_failures, ep.last_success_at = 0, now
    else:
        _fail(db, d, ep, f"Your server answered HTTP {resp.status_code}", resp.status_code)
    db.commit()
    return d.status
