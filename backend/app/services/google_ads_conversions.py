"""Google Ads learns from real bookings (website growth #5): the Google twin of marketing_capi (Meta).

Settings (Website › Tracking, owner/manager, in `sites.tracking`, audited with the rest): the Google Ads tag id
"AW-..." + the conversion labels for "enquiry" and "begin checkout" (browser tags, sites `Consent.tsx`, only after the
visitor taps Accept), and for bookings the Google Ads customer id, optional manager (login) customer id, the
"Import from clicks" conversion action id and the upload switch. Bookings have NO browser tag: the upload covers
website, WhatsApp, phone and manual bookings alike, and a second (tag) action would count each booking twice.

Connection: the owner signs in with Google (OAuth, scope datamanager, offline). Only the refresh + access tokens are
kept, Fernet-encrypted in an `Integration` kind `google_data_manager` (shown on the Integrations page); HAIP never asks
for or stores a Google password. A rejected token turns the integration `error` with the reason (Integrations health).

Click ids: the site keeps gclid / gbraid / wbraid from the landing URL only after the visitor accepted the cookie banner
and sends them with the enquiry / booking form (`_AdIds`, kept only when `analytics_consent`), or, for a WhatsApp button,
as an 8-letter code added to the "(Ref ...)" text (`POST /public/sites/{host}/wa-click` keeps code -> click ids in
Redis for 30 days; `website_refs.stamp` reads it when the chat's lead exists). Stored on the lead as
`inquiries.custom_fields["google_click"]` (the latest click wins: it is the one Google credits).

Uploads (one `website_events` row per booking, event_id "gads:stay:<id>", so each booking is uploaded once): every
booking made in the last 7 days that is not cancelled and has an amount. Value = the booking total + add-ons in INR
(booking_service.financials_for; a security deposit is never part of it), transactionId "stay:<id>" (Google's dedup),
the click id when known, and the guest's phone (E.164 with "+") / email (lower case, no spaces; Gmail: no dots or
"+tag" before the @), SHA-256 hex. Only for guests whose latest MARKETING consent is granted (marketing_capi.consented,
the Meta rule: sharing with an ad platform is marketing), re-checked at send; else `skipped` and nothing about the
guest leaves HAIP. Consent sent: adUserData GRANTED (they agreed), adPersonalization DENIED (nobody asked them about ad
personalisation; it does not affect conversion measurement). One request per booking; failures back off 5, 10, 20,
40 min (5 tries). Sent by the beat `website.send_events` (queue default), next to Meta and GA4.
"""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import google_data_manager as gdm
from app.adapters.instagram.publishing import PublishError
from app.core.audit import append_audit
from app.core.config import settings
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.integration import Integration
from app.models.property import Stay
from app.models.tenant import Tenant
from app.models.website import Site, WebsiteEvent
from app.services import marketing_capi, phone_identity

log = structlog.get_logger()

KIND = "google_data_manager"
PREFIX = "gads:"
_STAY = f"{PREFIX}stay:"
WINDOW = timedelta(days=7)
BATCH = 50
MAX_TRIES = 5
BACKOFF = timedelta(minutes=5)
CLICK_KEYS = ("gclid", "gbraid", "wbraid")
WA_CODE = re.compile(r"^[A-Z0-9]{8}$")
WA_TTL = 30 * 24 * 3600
_SOURCE = {
    InquirySource.WEBSITE: "WEB",
    InquirySource.PHONE: "PHONE",
    InquirySource.WA_DIRECT: "MESSAGE",
    InquirySource.CLICK_TO_WA: "MESSAGE",
    InquirySource.META_IG: "MESSAGE",
    InquirySource.META_FB: "MESSAGE",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


# ─── settings + connection ─────────────────────────────────────────────────────────────────────────────


def tracking_settings(site: Site) -> dict:
    t = site.tracking or {}
    keys = (
        "gads_id",
        "gads_enquiry_label",
        "gads_checkout_label",
        "gads_customer_id",
        "gads_login_customer_id",
        "gads_booking_action_id",
    )
    return {**{k: t.get(k) for k in keys}, "gads_upload_enabled": bool(t.get("gads_upload_enabled"))}


def _client() -> tuple[str, str]:
    if settings.GOOGLE_DATA_MANAGER_CLIENT_ID and settings.GOOGLE_DATA_MANAGER_CLIENT_SECRET:
        return settings.GOOGLE_DATA_MANAGER_CLIENT_ID, settings.GOOGLE_DATA_MANAGER_CLIENT_SECRET
    return settings.GOOGLE_BUSINESS_CLIENT_ID, settings.GOOGLE_BUSINESS_CLIENT_SECRET


def available() -> bool:
    return bool(all(_client()) and settings.API_BASE_URL)


def connection(db: Session, tenant_id: str, *, lock: bool = False) -> Integration | None:
    q = db.query(Integration).filter(
        Integration.tenant_id == tenant_id, Integration.kind == KIND, Integration.status.in_(("active", "error"))
    )
    return (q.with_for_update() if lock else q).first()


def status(db: Session, tenant_id: str) -> dict:
    integ = connection(db, tenant_id)
    return {
        "available": available(),
        "connected": integ is not None,
        "status": integ.status if integ else "disconnected",
        "last_error": (integ.config or {}).get("last_error") if integ else None,
        "last_upload_at": (integ.config or {}).get("last_upload_at") if integ else None,
    }


def upload_ready(site: Site, integ: Integration | None) -> bool:
    t = tracking_settings(site)
    return bool(
        t["gads_upload_enabled"]
        and t["gads_customer_id"]
        and t["gads_booking_action_id"]
        and integ is not None
        and integ.credentials_kms_blob
    )


def _callback() -> str:
    return f"{(settings.API_BASE_URL or '').rstrip('/')}/api/v1/websites/google-ads/oauth-callback"


def start(tenant_id: str, user_id: str) -> str:
    from app.services.marketing_channel_connections import _state
    from app.services.website_service import WebsiteError

    if not available():
        raise WebsiteError(503, "google_not_configured", "Google Ads uploads are not set up on this HAIP server yet.")
    return gdm.authorize_url(_client()[0], _callback(), _state("gdm", tenant_id, user_id))


def _store(integ: Integration, tok: dict, refresh_token: str | None) -> None:
    integ.credentials_kms_blob = encrypt_credentials(
        {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token") or refresh_token}
    )
    integ.config = {
        **(integ.config or {}),
        "expires_at": (_now() + timedelta(seconds=int(tok.get("expires_in") or 3600))).isoformat(),
    }


def finish(db: Session, code: str, state: str, *, http: httpx.Client | None = None) -> str:
    """OAuth callback: tokens encrypted on the tenant's integration. The state names the tenant + who started it."""
    from app.services.marketing_channel_connections import _take
    from app.services.website_service import WebsiteError

    ctx = _take("gdm", state)
    client_id, secret = _client()
    try:
        tok = gdm.exchange_code(client_id, secret, code, _callback(), client=http)
    except PublishError as exc:
        log.warning("google_ads_oauth_failed", tenant_id=ctx["tenant_id"], error=type(exc).__name__)
        raise WebsiteError(502, "google_login_failed", "Google did not accept the login.") from None
    if not tok.get("refresh_token"):
        raise WebsiteError(
            422,
            "no_refresh_token",
            "Google did not allow offline access. Remove HAIP from your Google "
            "account's connected apps and connect again.",
        )
    integ = db.query(Integration).filter_by(tenant_id=ctx["tenant_id"], kind=KIND).first() or Integration(
        tenant_id=ctx["tenant_id"], kind=KIND
    )
    integ.status = "active"
    integ.config = {k: v for k, v in (integ.config or {}).items() if k != "last_error"}
    _store(integ, tok, None)
    db.add(integ)
    db.flush()
    append_audit(
        db,
        tenant_id=ctx["tenant_id"],
        action="website.google_ads_connected",
        actor_user_id=ctx["user_id"],
        target_type="integration",
        target_id=integ.id,
        payload={},
    )
    return ctx["tenant_id"]


def _access_token(db: Session, integ: Integration, http: httpx.Client | None) -> str:
    creds = decrypt_credentials(integ.credentials_kms_blob)
    expires = (integ.config or {}).get("expires_at")
    if expires and datetime.fromisoformat(expires) > _now() + timedelta(minutes=5):
        return creds["access_token"]
    client_id, secret = _client()
    try:
        tok = gdm.refresh(client_id, secret, creds["refresh_token"], client=http)
    except PublishError as exc:
        # A revoked grant is a 400 invalid_grant: not transient = the owner must connect again.
        raise gdm.DataManagerError(
            "Google refused HAIP's saved login", transient=exc.transient, auth=not exc.transient
        ) from None
    _store(integ, tok, creds["refresh_token"])
    return tok["access_token"]


# ─── click ids ─────────────────────────────────────────────────────────────────────────────────────────


def click_from(body) -> dict | None:
    """Click ids from a website form, only when the visitor accepted the cookie banner."""
    if not getattr(body, "analytics_consent", False):
        return None
    click = {k: getattr(body, k, None) for k in CLICK_KEYS if getattr(body, k, None)}
    return click or None


def stamp(db: Session, inquiry: Inquiry | None, click: dict | None, *, via: str) -> bool:
    if inquiry is None or not click:
        return False
    keep = {k: str(v)[:200] for k, v in click.items() if k in CLICK_KEYS and v}
    if not keep:
        return False
    inquiry.custom_fields = {
        **(inquiry.custom_fields or {}),
        "google_click": {**keep, "at": _now().isoformat(), "via": via},
    }
    db.flush()
    return True


def _redis():
    from app.services.marketing_channel_connections import _redis as r

    return r()


def remember_wa_click(tenant_id: str, code: str, click: dict) -> bool:
    """The site's WhatsApp button added "-<code>" to its Ref; keep code -> click ids for 30 days (first write wins)."""
    if not WA_CODE.match(code or "") or not click:
        return False
    try:
        return bool(_redis().set(f"gads:wa:{tenant_id}:{code}", json.dumps(click), ex=WA_TTL, nx=True))
    except Exception:  # noqa: BLE001 -- attribution is best effort; a chat must never fail on it
        log.warning("google_ads_wa_click_store_failed", tenant_id=tenant_id)
        return False


def stamp_from_code(db: Session, tenant_id: str, inquiry: Inquiry, code: str | None) -> bool:
    if not code or not WA_CODE.match(code):
        return False
    try:
        from app.services.marketing_channel_connections import _TAKE_ONCE

        raw = _redis().eval(_TAKE_ONCE, 1, f"gads:wa:{tenant_id}:{code}")
    except Exception:  # noqa: BLE001
        log.warning("google_ads_wa_click_read_failed", tenant_id=tenant_id)
        return False
    if not raw:
        return False
    return stamp(db, inquiry, json.loads(raw), via="whatsapp")


# ─── uploads ───────────────────────────────────────────────────────────────────────────────────────────


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalise_email(raw: str | None) -> str | None:
    e = re.sub(r"\s+", "", raw or "").lower()
    if e.count("@") != 1:
        return None
    local, domain = e.split("@")
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}" if local and domain else None


def user_identifiers(guest: Guest) -> list[dict]:
    out = []
    phone = phone_identity.normalize(guest.phone, "IN")
    if phone:
        out.append({"phoneNumber": _sha(phone if phone.startswith("+") else f"+{phone}")})
    email = normalise_email(guest.email)
    if email:
        out.append({"emailAddress": _sha(email)})
    return out


def event_for(stay: Stay, guest: Guest, inquiry: Inquiry | None, value: Decimal) -> dict:
    ev: dict = {
        "transactionId": f"stay:{stay.id}",
        "eventTimestamp": _aware(stay.created_at).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "conversionValue": float(value),
        "currency": (stay.currency or "INR").upper(),
        "eventSource": _SOURCE.get(inquiry.source, "OTHER") if inquiry is not None else "OTHER",
    }
    click = ((inquiry.custom_fields or {}).get("google_click") or {}) if inquiry is not None else {}
    ids = {k: click[k] for k in CLICK_KEYS if click.get(k)}
    if ids:
        ev["adIdentifiers"] = ids
    found = user_identifiers(guest)
    if found:
        ev["userData"] = {"userIdentifiers": found}
    return ev


def request_body(site: Site, event: dict) -> dict:
    t = tracking_settings(site)
    return {
        "destinations": [
            {
                "operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": t["gads_customer_id"]},
                "loginAccount": {
                    "accountType": "GOOGLE_ADS",
                    "accountId": t["gads_login_customer_id"] or t["gads_customer_id"],
                },
                "productDestinationId": t["gads_booking_action_id"],
            }
        ],
        "encoding": "HEX",
        "consent": {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_DENIED"},
        "events": [event],
    }


def _values(db: Session, tenant_id: str, stays: list[Stay]) -> dict[str, Decimal]:
    from app.services.booking_service import financials_for

    return {sid: Decimal(str(f["total"])) for sid, f in financials_for(db, tenant_id, stays).items()}


def queue_new(db: Session, tenant: Tenant, site: Site, *, now: datetime | None = None) -> int:
    """Decide every booking of the last 7 days that has no Google row yet. Returns how many are pending."""
    now = now or _now()
    stays = (
        db.query(Stay)
        .filter(Stay.tenant_id == tenant.id, Stay.created_at >= now - WINDOW)
        .order_by(Stay.created_at.asc())
        .limit(500)
        .all()
    )
    ids = [f"{_STAY}{s.id}" for s in stays]
    seen = (
        {
            e
            for (e,) in db.query(WebsiteEvent.event_id).filter(
                WebsiteEvent.tenant_id == tenant.id, WebsiteEvent.event_id.in_(ids)
            )
        }
        if ids
        else set()
    )
    stays = [s for s in stays if f"{_STAY}{s.id}" not in seen]
    if not stays:
        return 0
    ok = marketing_capi.consented(db, tenant.id, list({s.guest_id for s in stays}))
    values = _values(db, tenant.id, stays)
    pending = 0
    for s in stays:
        value = values.get(s.id) or Decimal("0")
        reason = (
            "cancelled"
            if s.status == "cancelled"
            else "no amount"
            if value <= 0
            else "no marketing consent"
            if s.guest_id not in ok
            else None
        )
        row = WebsiteEvent(
            tenant_id=tenant.id,
            site_id=site.id,
            event_name="purchase",
            event_id=f"{_STAY}{s.id}",
            guest_id=s.guest_id,
            inquiry_id=s.inquiry_id,
            value=value,
            currency=(s.currency or "INR").upper(),
            status="skipped" if reason else "pending",
            reason=reason,
        )
        try:
            with db.begin_nested():
                db.add(row)
        except IntegrityError:  # another sweep decided it a moment ago
            continue
        pending += 0 if reason else 1
    db.flush()
    return pending


def _due(row: WebsiteEvent, now: datetime) -> bool:
    if row.status == "pending":
        return True
    return now >= _aware(row.updated_at) + BACKOFF * (2 ** max(row.tries - 1, 0))


def _mark_integration(integ: Integration, error: str | None, *, auth: bool = False) -> None:
    cfg = dict(integ.config or {})
    if error:
        cfg["last_error"] = error
        if auth:
            integ.status = "error"
    else:
        cfg.pop("last_error", None)
        cfg["last_upload_at"] = _now().isoformat()
        integ.status = "active"
        integ.last_health_at = _now().isoformat()
    integ.config = cfg


def send_tenant(
    db: Session,
    tenant: Tenant,
    *,
    post: Callable | None = None,
    http: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict:
    """Beat `website.send_events`: queue this tenant's new bookings, then upload the due ones (one request each)."""
    from app.services.website_service import get_site

    site = get_site(db, tenant.id)
    integ = connection(db, tenant.id, lock=True)
    if site is None or not upload_ready(site, integ):
        return {"sent": 0, "skipped": "off"}
    if integ.status == "error":
        return {"sent": 0, "skipped": "reconnect"}
    now = now or _now()
    queue_new(db, tenant, site, now=now)
    rows = [
        r
        for r in db.query(WebsiteEvent)
        .filter(
            WebsiteEvent.tenant_id == tenant.id,
            WebsiteEvent.event_id.startswith(PREFIX),
            WebsiteEvent.status.in_(("pending", "failed")),
            WebsiteEvent.tries < MAX_TRIES,
        )
        .order_by(WebsiteEvent.created_at.asc())
        .limit(BATCH)
        if _due(r, now)
    ]
    if not rows:
        db.commit()
        return {"sent": 0}
    stays = {
        s.id: s
        for s in db.query(Stay).filter(
            Stay.tenant_id == tenant.id, Stay.id.in_([r.event_id[len(_STAY) :] for r in rows])
        )
    }
    guests = {
        g.id: g
        for g in db.query(Guest).filter(
            Guest.tenant_id == tenant.id, Guest.id.in_({s.guest_id for s in stays.values()})
        )
    }
    inqs = {
        i.id: i
        for i in db.query(Inquiry).filter(
            Inquiry.tenant_id == tenant.id, Inquiry.id.in_({s.inquiry_id for s in stays.values() if s.inquiry_id})
        )
    }
    ok = marketing_capi.consented(db, tenant.id, list(guests))  # consent is re-checked at send time
    values = _values(db, tenant.id, list(stays.values()))
    send = post or (lambda tok, body: gdm.ingest(tok, body, http))
    sent = failed = 0
    try:
        token = _access_token(db, integ, http)
    except gdm.DataManagerError as exc:
        _mark_integration(integ, str(exc), auth=exc.auth)
        db.commit()
        log.warning("google_ads_token_failed", tenant_id=tenant.id, auth=exc.auth)
        return {"sent": 0, "error": "token"}
    for r in rows:
        s = stays.get(r.event_id[len(_STAY) :])
        g = guests.get(s.guest_id) if s else None
        if s is None or g is None or s.status == "cancelled" or g.id not in ok:
            r.status = "skipped"
            r.reason = "no marketing consent" if g is not None and s.status != "cancelled" else "booking changed"
            continue
        ev = event_for(s, g, inqs.get(s.inquiry_id), values.get(s.id) or r.value)
        if "adIdentifiers" not in ev and "userData" not in ev:
            r.status, r.reason = "skipped", "nothing Google can match"
            continue
        r.value = Decimal(str(ev["conversionValue"]))
        try:
            send(token, request_body(site, ev))
        except gdm.DataManagerError as exc:
            r.tries, r.status, r.reason = r.tries + 1, "failed", str(exc)[:300]
            failed += 1
            _mark_integration(integ, str(exc), auth=exc.auth)
            if exc.auth:
                break
            continue
        r.tries, r.status, r.sent_at, r.reason = r.tries + 1, "sent", _now(), None
        sent += 1
    if sent and not failed:
        _mark_integration(integ, None)
    if failed:
        log.warning("google_ads_upload_failed", tenant_id=tenant.id, failed=failed)
    if sent:
        append_audit(
            db,
            tenant_id=tenant.id,
            action="website.google_ads_sent",
            actor_user_id=None,
            target_type="site",
            target_id=site.id,
            payload={"actor": "system", "events": sent},
        )
    db.commit()
    return {"sent": sent, "failed": failed}
