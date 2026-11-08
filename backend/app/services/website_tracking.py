"""Website measurement (phase 2): Meta Pixel + Conversions API + GA4 for a HAIP site.

Settings (Website › Tracking, owner/manager, audited `website.tracking_changed`): `sites.tracking` holds the PUBLIC ids
(pixel_id, ga4_id) and the CAPI switch; the owner's Conversions API token is Fernet-encrypted in `sites.capi_token_enc`
and never returned (only `has_capi_token`).

Browser side (sites app `Consent.tsx`): nothing loads until the visitor accepts the DPDP cookie banner; the page-view
beacon stays cookie-less either way. The site fires Lead / InitiateCheckout / Purchase with the SAME event_id the server
returns, so Meta counts each pair once:
  Lead             "wl:<uuid>"     website enquiry, or a booking request (no payment)
  InitiateCheckout "wc:<hold id>"  a hold with a Razorpay link
  Purchase         "stay:<id>"     the booking the paid hold became (same id marketing_capi uses, so the two never double)
Server side: a `website_events` row per event, only while CAPI is on with a pixel id + token. It is `pending` when the
guest's latest MARKETING consent is granted (same rule as marketing_capi: sharing with Meta for ads is marketing),
else `skipped` and nothing about the guest leaves HAIP. Consent is re-checked at send. Identifiers are hashed
(marketing_capi.user_data); fbp/fbc only exist when the visitor accepted the banner. Beat `website.send_events` sends.

GA4 server purchase (Measurement Protocol): with a GA4 id + the owner's API secret (Fernet in `sites.ga4_secret_enc`,
never returned or logged), a paid website booking also gets a row "ga4:stay:<id>" sent to GA4 as `purchase` with
transaction_id "stay:<id>" = the browser's, so GA4 counts it once even when the guest never comes back from Razorpay.
Only when the visitor accepted the cookie banner (`booking_holds.analytics_consent`, set at checkout); client_id = the
_ga cookie's, else one HAIP generates (GA4 then sees a new user for that purchase). Value = the hold total in INR (GST
included; a security deposit is never part of it). Fixed host, no redirects; failures back off (5, 10, 20, 40 min).
"""

import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.website import Site, WebsiteEvent
from app.services import marketing_capi

log = structlog.get_logger()

WINDOW = timedelta(days=7)
BATCH = 100
MAX_TRIES = 5
GA4_URL = "https://www.google-analytics.com/mp/collect"  # fixed: nothing a person types reaches the URL (no SSRF)
GA4_WINDOW = timedelta(hours=72)  # Measurement Protocol drops events timestamped more than 72 h back
GA4_BACKOFF = timedelta(minutes=5)
GA4_PREFIX = "ga4:"


def _now() -> datetime:
    return datetime.now(UTC)


def settings_out(site: Site) -> dict:
    t = site.tracking or {}
    return {
        "pixel_id": t.get("pixel_id"),
        "ga4_id": t.get("ga4_id"),
        "capi_enabled": bool(t.get("capi_enabled")),
        "capi_test_code": t.get("capi_test_code"),
        "has_capi_token": bool(site.capi_token_enc),
        "has_ga4_api_secret": bool(site.ga4_secret_enc),
        "ga4_server": ga4_on(site),
    }


def public(site: Site) -> dict:
    """What the guest's browser may know: the two public ids (empty = no banner, nothing loads)."""
    t = site.tracking or {}
    return {k: t[k] for k in ("pixel_id", "ga4_id") if t.get(k)}


def update(db: Session, site: Site, body, *, actor_id: str) -> dict:
    before = settings_out(site)
    site.tracking = {
        "pixel_id": body.pixel_id,
        "ga4_id": body.ga4_id,
        "capi_enabled": body.capi_enabled,
        "capi_test_code": body.capi_test_code,
    }
    if body.capi_token is not None:
        token = body.capi_token.strip()
        site.capi_token_enc = encrypt_credentials({"token": token}).decode() if token else None
    if body.ga4_api_secret is not None:
        secret = body.ga4_api_secret.strip()
        site.ga4_secret_enc = encrypt_credentials({"secret": secret}).decode() if secret else None
    after = settings_out(site)
    append_audit(
        db,
        tenant_id=site.tenant_id,
        actor_user_id=actor_id,
        action="website.tracking_changed",
        target_type="site",
        target_id=site.id,
        payload={"changed": {k: [before[k], v] for k, v in after.items() if before[k] != v}},
    )
    db.flush()
    return after


def _token(site: Site) -> str | None:
    if not site.capi_token_enc:
        return None
    try:
        return decrypt_credentials(site.capi_token_enc.encode()).get("token") or None
    except Exception:  # noqa: BLE001 -- a key rotation without re-entry: treat as no token, logged
        log.error("website_capi_token_unreadable", tenant_id=site.tenant_id, site_id=site.id)
        return None


def capi_on(site: Site) -> bool:
    t = site.tracking or {}
    return bool(t.get("capi_enabled") and t.get("pixel_id") and site.capi_token_enc)


def new_lead_id() -> str:
    return f"wl:{uuid.uuid4()}"


def record(
    db: Session,
    site: Site,
    *,
    name: str,
    event_id: str,
    guest_id: str | None,
    inquiry_id: str | None = None,
    hold_id: str | None = None,
    value=None,
    source_url: str | None = None,
    user_agent: str | None = None,
    fbp: str | None = None,
    fbc: str | None = None,
) -> WebsiteEvent | None:
    """Queue one server-side event (no row when CAPI is off). Idempotent on (tenant, event_id)."""
    if not capi_on(site):
        return None
    ok = bool(guest_id) and guest_id in marketing_capi.consented(db, site.tenant_id, [guest_id])
    row = WebsiteEvent(
        tenant_id=site.tenant_id,
        site_id=site.id,
        event_name=name,
        event_id=event_id[:80],
        guest_id=guest_id,
        inquiry_id=inquiry_id,
        hold_id=hold_id,
        value=Decimal(str(value)) if value is not None else None,
        currency="INR",
        source_url=(source_url or "")[:500] or None,
        client_user_agent=(user_agent or "")[:300] or None,
        fbp=fbp,
        fbc=fbc,
        status="pending" if ok else "skipped",
        reason=None if ok else "no marketing consent",
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        return db.query(WebsiteEvent).filter_by(tenant_id=site.tenant_id, event_id=event_id[:80]).first()
    return row


def purchase(db: Session, site: Site, hold, stay) -> WebsiteEvent | None:
    """The paid hold became a booking: Purchase with the stay's own id; browser ids from the hold's checkout event."""
    first = db.query(WebsiteEvent).filter_by(tenant_id=site.tenant_id, event_id=f"wc:{hold.id}").first()
    return record(
        db,
        site,
        name="Purchase",
        event_id=f"stay:{stay.id}",
        guest_id=hold.guest_id,
        inquiry_id=hold.inquiry_id,
        hold_id=hold.id,
        value=hold.total,
        source_url=first.source_url if first else None,
        user_agent=first.client_user_agent if first else None,
        fbp=first.fbp if first else None,
        fbc=first.fbc if first else None,
    )


def _event(row: WebsiteEvent, guest: Guest) -> dict:
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
    ud = marketing_capi.user_data(guest)
    for k, v in (("client_user_agent", row.client_user_agent), ("fbp", row.fbp), ("fbc", row.fbc)):
        if v:
            ud[k] = v
    ev = {
        "event_name": row.event_name,
        "event_time": int(created.timestamp()),
        "event_id": row.event_id,
        "action_source": "website",
        "user_data": ud,
    }
    if row.source_url:
        ev["event_source_url"] = row.source_url
    if row.value is not None:
        ev["custom_data"] = {"value": float(row.value), "currency": row.currency or "INR"}
    return ev


def _writer(token: str):
    from app.adapters.marketing.meta_ads_write import MetaAdsWriter

    return MetaAdsWriter(token, "")  # send_events needs only the token and the dataset (pixel) id


def send_tenant(db: Session, tenant: Tenant, *, writer_factory: Callable | None = None) -> dict:
    from app.adapters.marketing.meta_ads import MetaAdsError
    from app.services.website_service import get_site

    site = get_site(db, tenant.id)
    if site is None or not capi_on(site):
        return {"sent": 0, "skipped": "off"}
    rows = (
        db.query(WebsiteEvent)
        .filter(
            WebsiteEvent.tenant_id == tenant.id,
            WebsiteEvent.site_id == site.id,
            WebsiteEvent.status.in_(("pending", "failed")),
            WebsiteEvent.tries < MAX_TRIES,
            ~WebsiteEvent.event_id.startswith(GA4_PREFIX),
        )
        .order_by(WebsiteEvent.created_at.asc())
        .limit(BATCH)
        .all()
    )
    if not rows:
        return {"sent": 0}
    token = _token(site)
    if not token:
        return {"sent": 0, "skipped": "no token"}
    guests = {
        g.id: g
        for g in db.query(Guest).filter(
            Guest.tenant_id == tenant.id, Guest.id.in_({r.guest_id for r in rows if r.guest_id})
        )
    }
    ok = marketing_capi.consented(db, tenant.id, list(guests))  # re-checked at send time
    cutoff = _now() - WINDOW
    batch, events = [], []
    for r in rows:
        g = guests.get(r.guest_id)
        made = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)
        if g is None or g.id not in ok:
            r.status, r.reason = "skipped", "no marketing consent"
        elif made < cutoff:
            r.status, r.reason = "skipped", "too old for Meta"
        else:
            batch.append(r)
            events.append(_event(r, g))
    if not events:
        db.commit()
        return {"sent": 0}
    writer = (writer_factory or _writer)(token)
    try:
        resp = writer.send_events(
            (site.tracking or {})["pixel_id"], events, test_code=(site.tracking or {}).get("capi_test_code")
        )
    except MetaAdsError as exc:
        for r in batch:
            r.tries, r.status, r.reason = r.tries + 1, "failed", str(exc)[:300]
        db.commit()
        log.warning("website_capi_failed", tenant_id=tenant.id, error=str(exc)[:200])
        return {"sent": 0, "error": str(exc)[:200]}
    finally:
        writer.close()
    when = _now()
    for r in batch:
        r.tries, r.status, r.sent_at, r.reason = r.tries + 1, "sent", when, None
    append_audit(
        db,
        tenant_id=tenant.id,
        action="website.capi_sent",
        actor_user_id=None,
        target_type="site",
        target_id=site.id,
        payload={"actor": "system", "events": len(batch), "received": resp.get("events_received")},
    )
    db.commit()
    return {"sent": len(batch), "received": resp.get("events_received")}


def recent(db: Session, site: Site, limit: int = 30) -> list[dict]:
    rows = (
        db.query(WebsiteEvent)
        .filter_by(tenant_id=site.tenant_id, site_id=site.id)
        .order_by(WebsiteEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "channel": "ga4" if r.event_id.startswith(GA4_PREFIX) else "meta",
            "event_name": r.event_name,
            "status": r.status,
            "reason": r.reason,
            "sent_at": r.sent_at,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ─── GA4 Measurement Protocol (server purchase) ───────────────────────────────────────────────────────


class Ga4Error(Exception):
    pass


def ga4_on(site: Site) -> bool:
    return bool((site.tracking or {}).get("ga4_id") and site.ga4_secret_enc)


def _ga4_secret(site: Site) -> str | None:
    if not site.ga4_secret_enc:
        return None
    try:
        return decrypt_credentials(site.ga4_secret_enc.encode()).get("secret") or None
    except Exception:  # noqa: BLE001 -- a key rotation without re-entry: treat as no secret, logged
        log.error("website_ga4_secret_unreadable", tenant_id=site.tenant_id, site_id=site.id)
        return None


def new_client_id() -> str:
    """GA4's own shape "<random>.<seconds>", for a consenting visitor whose _ga cookie did not reach us."""
    return f"{secrets.randbelow(2**31)}.{int(_now().timestamp())}"


def ga4_purchase(db: Session, site: Site, hold, stay) -> WebsiteEvent | None:
    """Queue the GA4 server purchase for a paid hold (no row when GA4 server sending is off). Idempotent per stay."""
    if not ga4_on(site):
        return None
    ok = bool(hold.analytics_consent)
    event_id = f"{GA4_PREFIX}stay:{stay.id}"
    row = WebsiteEvent(
        tenant_id=site.tenant_id,
        site_id=site.id,
        event_name="purchase",
        event_id=event_id,
        guest_id=hold.guest_id,
        inquiry_id=hold.inquiry_id,
        hold_id=hold.id,
        value=Decimal(str(hold.total)),
        currency="INR",
        ga_client_id=(hold.ga_client_id or new_client_id()) if ok else None,
        status="pending" if ok else "skipped",
        reason=None if ok else "no analytics consent",
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        return db.query(WebsiteEvent).filter_by(tenant_id=site.tenant_id, event_id=event_id).first()
    return row


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _ga4_body(row: WebsiteEvent) -> dict:
    return {
        "client_id": row.ga_client_id,
        "timestamp_micros": int(_aware(row.created_at).timestamp() * 1_000_000),
        "consent": {"ad_user_data": "GRANTED", "ad_personalization": "GRANTED"},  # rows exist only after "Accept"
        "events": [
            {
                "name": "purchase",
                "params": {
                    "transaction_id": row.event_id[len(GA4_PREFIX) :],  # "stay:<id>", the browser event's id
                    "value": float(row.value or 0),
                    "currency": row.currency or "INR",
                },
            }
        ],
    }


def _ga4_post(measurement_id: str, secret: str, body: dict) -> None:
    import httpx

    resp = httpx.post(
        GA4_URL,
        params={"measurement_id": measurement_id, "api_secret": secret},
        json=body,
        timeout=10,
        follow_redirects=False,
    )
    if resp.status_code >= 300:
        raise Ga4Error(f"GA4 answered {resp.status_code}")


def _ga4_due(row: WebsiteEvent, now: datetime) -> bool:
    if row.status == "pending":
        return True
    return now >= _aware(row.updated_at) + GA4_BACKOFF * (2 ** max(row.tries - 1, 0))


def send_ga4_tenant(db: Session, tenant: Tenant, *, post: Callable | None = None) -> dict:
    """Beat `website.send_events`: this tenant's due GA4 rows, one request each (MP takes one client per call).
    A failure's reason is the error class or status only: the request URL carries the API secret."""
    from app.services.website_service import get_site

    site = get_site(db, tenant.id)
    if site is None or not ga4_on(site):
        return {"sent": 0, "skipped": "off"}
    now = _now()
    rows = [
        r
        for r in db.query(WebsiteEvent)
        .filter(
            WebsiteEvent.tenant_id == tenant.id,
            WebsiteEvent.site_id == site.id,
            WebsiteEvent.event_id.startswith(GA4_PREFIX),
            WebsiteEvent.status.in_(("pending", "failed")),
            WebsiteEvent.tries < MAX_TRIES,
        )
        .order_by(WebsiteEvent.created_at.asc())
        .limit(BATCH)
        if _ga4_due(r, now)
    ]
    if not rows:
        return {"sent": 0}
    secret = _ga4_secret(site)
    if not secret:
        return {"sent": 0, "skipped": "no secret"}
    measurement_id = (site.tracking or {})["ga4_id"]
    send = post or _ga4_post
    sent = failed = 0
    for r in rows:
        if _aware(r.created_at) < now - GA4_WINDOW:
            r.status, r.reason = "skipped", "too old for GA4"
            continue
        try:
            send(measurement_id, secret, _ga4_body(r))
        except Exception as exc:  # noqa: BLE001 -- never str(exc) of an httpx error: it names the URL with the secret
            r.tries, r.status = r.tries + 1, "failed"
            r.reason = str(exc)[:300] if isinstance(exc, Ga4Error) else type(exc).__name__
            failed += 1
            continue
        r.tries, r.status, r.sent_at, r.reason = r.tries + 1, "sent", _now(), None
        sent += 1
    if failed:
        log.warning("website_ga4_failed", tenant_id=tenant.id, failed=failed)
    if sent:
        append_audit(
            db,
            tenant_id=tenant.id,
            action="website.ga4_sent",
            actor_user_id=None,
            target_type="site",
            target_id=site.id,
            payload={"actor": "system", "events": sent},
        )
    db.commit()
    return {"sent": sent, "failed": failed}
