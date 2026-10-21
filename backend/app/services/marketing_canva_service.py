"""Canva for Marketing Studio (agency M2b): connect a workspace's Canva account, list its brand templates, and fill one
from a draft (headline, body, call to action, photo). The export is saved in the library as an active photo
(source "canva") -- the owner's own template, so no AI approval step; it is used with the "photo only" look because
the text is already in the design. The Canva edit link is kept so the owner can adjust the design in Canva.

Tokens: encrypted in Integration(kind="canva"). Canva refresh tokens are single use, so a refresh happens under a
row lock (PostgreSQL) and the new pair is stored before the access token is used.
"""
import io
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from PIL import Image
from sqlalchemy.orm import Session

from app.adapters import canva as canva_api
from app.core.audit import append_audit
from app.core.config import settings
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration
from app.models.marketing import MarketingCreativeJob
from app.models.tenant import Tenant
from app.services import marketing_content_service as content_svc
from app.services import media_library_service as library
from app.services.marketing_content_service import MarketingError
from app.services.marketing_render import frames

log = structlog.get_logger()

KIND = "canva"
STATE_TTL = 600
_TAKE_ONCE = "local v = redis.call('GET', KEYS[1]); if v then redis.call('DEL', KEYS[1]) end; return v"


def configured() -> bool:
    return bool(settings.CANVA_CLIENT_ID and settings.CANVA_CLIENT_SECRET and settings.API_BASE_URL)


def callback_url() -> str:
    return f"{(settings.API_BASE_URL or '').rstrip('/')}/api/v1/marketing/studio/canva/oauth-callback"


def connection(db: Session, tenant_id: str, *, lock: bool = False) -> Optional[Integration]:
    q = db.query(Integration).filter_by(tenant_id=tenant_id, kind=KIND, status="active")
    return (q.with_for_update() if lock else q).first()


def _redis():
    import redis
    return redis.Redis.from_url(settings.REDIS_URL, socket_timeout=3)


def start_oauth(tenant_id: str, user_id: str) -> str:
    """The Canva consent URL. The PKCE verifier and who asked are kept in Redis under a single-use state."""
    if not configured():
        raise MarketingError(503, "canva_not_configured", "Canva is not set up on this HAIP server yet.")
    verifier, challenge = canva_api.pkce_pair()
    nonce = secrets.token_urlsafe(32)
    _redis().setex(f"oauth:canva:{nonce}", STATE_TTL, json.dumps({"tenant_id": tenant_id, "user_id": user_id,
                                                                   "verifier": verifier}))
    return canva_api.authorize_url(settings.CANVA_CLIENT_ID, callback_url(), nonce, challenge)


def finish_oauth(db: Session, code: str, state: str, *, http=None) -> str:
    """Exchange the code; store the tokens. Returns the tenant id. Raises MarketingError."""
    raw = _redis().eval(_TAKE_ONCE, 1, f"oauth:canva:{state}")
    if not raw:
        raise MarketingError(400, "state_expired", "This Canva login link expired or was already used. Try again.")
    ctx = json.loads(raw)
    try:
        tok = canva_api.exchange_code(settings.CANVA_CLIENT_ID, settings.CANVA_CLIENT_SECRET, code, ctx["verifier"],
                                      callback_url(), client=http)
    except canva_api.CanvaError as exc:
        log.warning("canva_oauth_failed", tenant_id=ctx["tenant_id"], error=str(exc)[:200])
        raise MarketingError(502, "canva_login_failed", "Canva did not accept the login.")
    integ = connection(db, ctx["tenant_id"]) or Integration(tenant_id=ctx["tenant_id"], kind=KIND)
    _store_tokens(integ, tok)
    integ.status = "active"
    db.add(integ)
    db.flush()
    append_audit(db, tenant_id=ctx["tenant_id"], action="marketing.canva.connected", actor_user_id=ctx["user_id"],
                 target_type="integration", target_id=integ.id, payload={"scope": tok.get("scope")})
    return ctx["tenant_id"]


def _store_tokens(integ: Integration, tok: dict) -> None:
    integ.credentials_kms_blob = encrypt_credentials({"access_token": tok["access_token"], "refresh_token": tok["refresh_token"]})
    integ.config = {**(integ.config or {}), "scope": tok.get("scope"),
                    "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in") or 3600))).isoformat()}


def disconnect(db: Session, tenant_id: str, actor_id: str) -> bool:
    integ = connection(db, tenant_id)
    if integ is None:
        return False
    integ.status, integ.credentials_kms_blob = "disconnected", None
    append_audit(db, tenant_id=tenant_id, action="marketing.canva.disconnected", actor_user_id=actor_id,
                 target_type="integration", target_id=integ.id, payload={})
    return True


def client(db: Session, tenant_id: str, *, http=None) -> canva_api.Canva:
    """A Canva client with a fresh access token. Refreshes (and commits the new single-use refresh token) when needed."""
    integ = connection(db, tenant_id, lock=True)
    if integ is None or not integ.credentials_kms_blob:
        raise MarketingError(409, "canva_not_connected", "Connect Canva first.")
    creds = decrypt_credentials(integ.credentials_kms_blob)
    expires = (integ.config or {}).get("expires_at")
    if not expires or datetime.fromisoformat(expires) < datetime.now(timezone.utc) + timedelta(minutes=5):
        try:
            tok = canva_api.refresh(settings.CANVA_CLIENT_ID, settings.CANVA_CLIENT_SECRET, creds["refresh_token"], client=http)
        except canva_api.CanvaError as exc:
            if not exc.transient:
                integ.status = "error"
                db.commit()
                raise MarketingError(409, "canva_reconnect", "Canva needs to be connected again.")
            raise
        _store_tokens(integ, tok)
        db.commit()                              # the old refresh token is now spent: keep the new one first
        creds = {"access_token": tok["access_token"]}
    return canva_api.Canva(creds["access_token"], client=http)


# ── Fill a template from a draft ────────────────────────────────────────────────────────────────────────────────────

_ROLES = {"headline": ("headline", "title", "heading"), "sub": ("body", "sub", "text", "description", "line"),
          "cta": ("cta", "button", "action"), "caption": ("caption",)}


def field_data(dataset: dict[str, str], kind: str, payload: dict, asset_ids: dict[str, str]) -> dict:
    """Map a template's data fields to the draft by field name; image fields get the draft's photos in order.
    Fields that match nothing are left out, so the template's own default shows."""
    fr = frames(kind, payload)
    first = fr[0] if fr else {}
    values = {"headline": first.get("headline"), "sub": first.get("sub"), "cta": first.get("cta"),
              "caption": (payload.get("caption") or "").split("\n", 1)[0] or None}
    photos = [asset_ids[f["asset_id"]] for f in fr if f.get("asset_id") in asset_ids]
    data: dict = {}
    used_photos = 0
    for name, ftype in dataset.items():
        low = name.lower()
        if ftype == "image" and photos:
            data[name] = {"type": "image", "asset_id": photos[min(used_photos, len(photos) - 1)]}
            used_photos += 1
        elif ftype == "text":
            role = next((r for r, keys in _ROLES.items() if any(k in low for k in keys)), None)
            if role and values.get(role):
                data[name] = {"type": "text", "text": values[role][:500]}
    return data


def request_design(db: Session, tenant: Tenant, item_id: str, template_id: str, actor_id: str) -> MarketingCreativeJob:
    item = content_svc.get_item(db, tenant.id, item_id)
    version = content_svc.get_version(db, tenant.id, item.current_version_id)
    if version is None:
        raise MarketingError(409, "no_version", "Write the draft first.")
    if connection(db, tenant.id) is None:
        raise MarketingError(409, "canva_not_connected", "Connect Canva first.")
    job = MarketingCreativeJob(tenant_id=tenant.id, provider="canva", kind="design", content_id=item.id,
                               inputs={"template_id": template_id, "version_id": version.id},
                               idempotency_key=uuid.uuid4().hex, created_by=actor_id)
    db.add(job)
    db.flush()
    return job


def run_design(db: Session, tenant: Tenant, job_id: str, *, http=None, read_bytes=None) -> MarketingCreativeJob:
    """Upload the draft's photos to Canva, autofill the template, export a JPEG into the library. Raises CanvaError
    (check .transient) for the caller to retry; anything permanent is recorded on the job."""
    job = db.query(MarketingCreativeJob).filter_by(id=job_id, tenant_id=tenant.id).one()
    if job.status == "ready":
        return job
    version = content_svc.get_version(db, tenant.id, job.inputs.get("version_id"))
    item = content_svc.get_item(db, tenant.id, job.content_id)
    job.status = "running"
    api = client(db, tenant.id, http=http)
    try:
        if not job.external_id:
            dataset = api.dataset(job.inputs["template_id"])
            from app.models.media_asset import MediaAsset
            ids = [f["asset_id"] for f in frames(item.kind, version.payload) if f.get("asset_id")]
            uploaded: dict[str, str] = {}
            if any(t == "image" for t in dataset.values()):
                for a in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant.id, MediaAsset.id.in_(ids),
                                                     MediaAsset.status == "active").limit(5):
                    uploaded[a.id] = api.upload_asset((read_bytes or library._read_object)(a.storage_key), f"haip-{a.id[:8]}")
            data = field_data(dataset, item.kind, version.payload, uploaded)
            if not data:
                raise canva_api.CanvaError("This template has no fields HAIP can fill (name them headline, body, cta, photo).",
                                           transient=False)
            design = api.autofill(job.inputs["template_id"], data, item.title)
            job.external_id, job.external_url = design.get("id"), design.get("url")
            db.commit()                          # saved before exporting: a retry exports this design, never a new one
        urls = api.export_jpg(job.external_id)
        if not urls:
            raise canva_api.CanvaError("Canva exported nothing.", transient=True)
        raw = api.download(urls[0])
    except canva_api.CanvaError as exc:
        if exc.transient:
            raise
        job.status, job.error = "failed", str(exc)[:2000]
        return job
    finally:
        api.close()
    with Image.open(io.BytesIO(raw)) as img:
        size = img.size
    asset = library._store(db, tenant.id, raw, "image/jpeg", "jpg", size, source="canva", actor_id=job.created_by,
                           alt_text=item.title[:300], property_id=item.property_id, status="active",
                           provenance={"canva_design_id": job.external_id, "canva_url": job.external_url,
                                       "template_id": job.inputs.get("template_id"), "content_id": item.id})
    job.status, job.asset_id, job.error = "ready", asset.id, None
    append_audit(db, tenant_id=tenant.id, action="marketing.canva.design_made", actor_user_id=job.created_by,
                 target_type="media_asset", target_id=asset.id, payload={"content_id": item.id, "design": job.external_id})
    return job
