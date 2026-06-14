"""Dograh voice AI webhook endpoint."""
import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.adapters.voice.dograh import DograhAdapter
from app.core.database import get_db
from app.core.encryption import decrypt_credentials
from app.models.call import Call
from app.models.tenant import Tenant
from app.workers.tasks.dograh_call_processor import process_dograh_call_completed
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks-dograh"])

_adapter = DograhAdapter()


@router.post("/dograh/{tenant_slug}")
async def dograh_webhook(
    tenant_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Receive call.completed webhook from Dograh.

    Security:
    1. Raw body read before JSON parse.
    2. Tenant resolved from slug — 404 if unknown.
    3. Per-tenant secret from dograh_webhook_secret_enc — 401 if missing.
    4. HMAC-SHA256 signature verified — 401 if invalid.
    5. Idempotency: duplicate dograh_call_id returns 200.
    6. Background task queued; always return 200.
    """
    # 1. Read raw body first (signature verification requires original bytes)
    body = await request.body()
    headers = dict(request.headers)

    # 2. Resolve tenant
    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if not tenant:
        log.warning("dograh_tenant_not_found", tenant_slug=tenant_slug)
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 3. Get per-tenant webhook secret
    secret = ""
    if tenant.dograh_webhook_secret_enc:
        blob = bytes(tenant.dograh_webhook_secret_enc) if isinstance(tenant.dograh_webhook_secret_enc, memoryview) else tenant.dograh_webhook_secret_enc
        creds = decrypt_credentials(blob)
        secret = creds.get("webhook_secret", "")

    if not secret:
        log.warning("dograh_webhook_secret_missing", tenant_slug=tenant_slug)
        raise HTTPException(status_code=401, detail="Dograh webhook secret not configured for this tenant")

    # 4. Verify signature
    if not _adapter.verify_webhook_signature(body, headers, secret=secret):
        log.warning("dograh_sig_invalid", tenant_slug=tenant_slug)
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 5. Parse payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        log.warning("dograh_invalid_json", tenant_slug=tenant_slug)
        return {"status": "ok"}

    call_id = payload.get("call_id", "")

    # 6. Idempotency check
    if call_id:
        existing = db.query(Call).filter(
            Call.tenant_id == tenant.id,
            Call.dograh_call_id == call_id,
        ).first()
        if existing:
            log.info("dograh_duplicate_call", call_id=call_id, tenant_slug=tenant_slug)
            return {"status": "ok"}

    # 7. Validate recording_url domain (SSRF guard) before passing to task
    recording_url = payload.get("recording_url")
    if recording_url and not _adapter.validate_recording_url(recording_url):
        log.warning("dograh_recording_url_rejected", tenant_slug=tenant_slug)
        payload = {**payload, "recording_url": None}

    # 8. Extract IVR routing metadata from extracted_variables
    ev = payload.get("extracted_variables") or {}
    dtmf_digit = ev.get("dtmf_digit")
    department = ev.get("department")
    if dtmf_digit is not None:
        payload = {**payload, "dtmf_digit": dtmf_digit, "department": department}

    # 9. Queue background task and return 200 immediately
    log.info("dograh_webhook_received", tenant_slug=tenant_slug, call_id=call_id)
    process_dograh_call_completed.delay(tenant_id=tenant.id, payload=payload)
    return {"status": "queued"}
