"""Yaad -> Google Calendar (owner, 15 Nov: the person picks which events go to Google; edits and deletes carry over).

Connection = Integration kind `google_calendar`, made by the person's own Google sign-in (same Google Cloud OAuth client as
the Business Profile, GOOGLE_BUSINESS_CLIENT_ID/SECRET, scope calendar.events, offline access; refresh token Fernet-
encrypted, never returned or logged; single-use state). Redirect URI to register in Google Cloud:
  {API_BASE_URL}/api/v1/me/calendar/google/oauth-callback
Sync is ONE-WAY, Yaad -> Google, one event at a time (task `personal.google_sync`):
  wanted (google on, event accepted)   -> create the Google copy, or update it
  not wanted (switched off, dismissed) -> delete the Google copy, forget its id
  deleted in Yaad                      -> delete the Google copy
Nothing goes to Google that the person did not switch on. Changes made inside Google are NOT read back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy.orm import Session

from app.adapters import google_business as gbp
from app.adapters import google_calendar as gcal
from app.adapters.instagram.publishing import PublishError
from app.core.audit import append_audit
from app.core.config import settings
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
from app.models.yaad_folder import YaadEvent
from app.services import marketing_channel_connections as conns
from app.services.marketing_content_service import MarketingError
from app.services.roster_service import tenant_tz

log = structlog.get_logger()

KIND = "google_calendar"
STATE = "gcal"


def available() -> bool:
    return conns.status_available_google()


def callback_url() -> str:
    return f"{(settings.API_BASE_URL or '').rstrip('/')}/api/v1/me/calendar/google/oauth-callback"


def start(tenant_id: str, user_id: str) -> str:
    if not available():
        raise MarketingError(503, "google_not_configured", "Google sign-in is not set up on this HAIP server yet.")
    return gbp.authorize_url(
        settings.GOOGLE_BUSINESS_CLIENT_ID, callback_url(), conns._state(STATE, tenant_id, user_id), scope=gcal.SCOPE
    )


def connection(db: Session, tenant_id: str, *, lock: bool = False) -> Integration | None:
    return conns.connection(db, tenant_id, KIND, lock=lock)


def finish(db: Session, code: str, state: str, *, http: httpx.Client | None = None) -> str:
    ctx = conns._take(STATE, state)
    try:
        tok = gbp.exchange_code(
            settings.GOOGLE_BUSINESS_CLIENT_ID,
            settings.GOOGLE_BUSINESS_CLIENT_SECRET,
            code,
            callback_url(),
            client=http,
        )
    except PublishError as exc:
        log.warning("google_calendar_oauth_failed", tenant_id=ctx["tenant_id"], status=exc.status)
        raise MarketingError(502, "google_login_failed", "Google did not accept the login.") from exc
    if not tok.get("refresh_token"):
        raise MarketingError(
            422,
            "no_refresh_token",
            "Google did not allow offline access. Remove HAIP from your Google account's connected apps and connect again.",
        )
    integ = connection(db, ctx["tenant_id"]) or Integration(tenant_id=ctx["tenant_id"], kind=KIND)
    integ.status = "active"
    conns._store_google(integ, tok, None)
    db.add(integ)
    db.flush()
    append_audit(
        db,
        tenant_id=ctx["tenant_id"],
        action="yaad.google_calendar.connected",
        actor_user_id=ctx["user_id"],
        target_type="integration",
        target_id=integ.id,
        payload={},
    )
    return ctx["tenant_id"]


def client(db: Session, tenant_id: str, *, http: httpx.Client | None = None) -> gcal.GoogleCalendar | None:
    """A client with a fresh access token, or None when Google Calendar is not connected."""
    integ = connection(db, tenant_id, lock=True)
    if integ is None or not integ.credentials_kms_blob:
        return None
    creds = decrypt_credentials(integ.credentials_kms_blob)
    expires = (integ.config or {}).get("expires_at")
    if not expires or datetime.fromisoformat(expires) < datetime.now(UTC) + timedelta(minutes=5):
        tok = gbp.refresh(
            settings.GOOGLE_BUSINESS_CLIENT_ID,
            settings.GOOGLE_BUSINESS_CLIENT_SECRET,
            creds["refresh_token"],
            client=http,
        )
        conns._store_google(integ, tok, creds["refresh_token"])
        db.flush()
        creds = {"access_token": tok["access_token"]}
    return gcal.GoogleCalendar(creds["access_token"], client=http)


def status(db: Session, tenant_id: str) -> dict:
    return {"available": available(), "connected": connection(db, tenant_id) is not None}


def disconnect(db: Session, tenant_id: str, actor_id: str) -> dict:
    """Stop syncing. Copies already in Google stay there; Yaad forgets their ids (a reconnect makes fresh copies)."""
    integ = connection(db, tenant_id)
    if integ is None:
        return {"disconnected": False}
    integ.status = "disconnected"
    integ.credentials_kms_blob = None
    db.query(YaadEvent).filter(YaadEvent.tenant_id == tenant_id, YaadEvent.google_event_id.isnot(None)).update(
        {YaadEvent.google_event_id: None, YaadEvent.google_synced_at: None}, synchronize_session=False
    )
    append_audit(
        db,
        tenant_id=tenant_id,
        action="yaad.google_calendar.disconnected",
        actor_user_id=actor_id,
        target_type="integration",
        target_id=integ.id,
        payload={},
    )
    return {"disconnected": True}


def wanted(e: YaadEvent) -> bool:
    return bool(e.google) and e.status == "accepted"


def sync_event(db: Session, tenant_id: str, event_id: str, *, api: gcal.GoogleCalendar | None = None) -> str:
    """Bring one event's Google copy in line with Yaad. Returns created | updated | deleted | skipped | not_connected.
    Raises PublishError when Google refuses (the caller stores the reason, a transient one is retried)."""
    e = db.query(YaadEvent).filter_by(id=event_id, tenant_id=tenant_id).first()
    if e is None:
        return "skipped"
    if not wanted(e) and not e.google_event_id:
        return "skipped"
    api = api or client(db, tenant_id)
    if api is None:
        return "not_connected"
    if not wanted(e):
        api.delete(e.google_event_id)
        e.google_event_id, e.google_synced_at, e.google_error = None, None, None
        return "deleted"
    body = gcal.event_body(
        title=e.title,
        day=e.day,
        start_time=e.start_time,
        place=e.place,
        notes=e.notes,
        people=e.people or [],
        tz=str(tenant_tz(db, tenant_id)),
    )
    if e.google_event_id:
        api.update(e.google_event_id, body)
        outcome = "updated"
    else:
        e.google_event_id = api.insert(body)
        outcome = "created"
    e.google_synced_at, e.google_error = datetime.now(UTC), None
    return outcome


def delete_copy(db: Session, tenant_id: str, google_event_id: str, *, api: gcal.GoogleCalendar | None = None) -> str:
    """The Yaad event is gone: delete its Google copy."""
    api = api or client(db, tenant_id)
    if api is None:
        return "not_connected"
    api.delete(google_event_id)
    return "deleted"
