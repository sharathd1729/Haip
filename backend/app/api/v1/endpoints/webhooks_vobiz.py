"""
Vobiz IVR webhooks — recording-only pass (no DTMF menu, no AI agent).

Vobiz's inbound flow is two separate webhooks, unlike CallerDesk/Acefone/
Mcube's single call-completed callback:

  1. Answer URL  — fires when the call arrives. HAIP replies with XML that
     starts a whole-session recording and dials the agent's mobile.
  2. Recording callback — fires once the (session-long) recording finishes,
     with the download URL and duration.

Since CallWebhookPayload needs from/to/duration/recording_url in one shot,
step 1's From/To/Direction are cached (keyed by CallUUID) and merged back in
at step 2, right before handing off to the same call_ingest pipeline every
other IVR provider uses.

Auth: same convention as Mcube (see McubeAdapter/VobizAdapter docstrings) —
an unguessable per-tenant secret embedded in the URL path itself, checked
with secrets.compare_digest. Vobiz's own X-Vobiz-Signature HMAC is not used
for authorization since it signs the URL, not the body.
"""
import secrets

from fastapi import APIRouter, Request, HTTPException, Depends, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.cache import get_cached, set_cached
from app.adapters.ivr import get_ivr_adapter
from app.models.tenant import Tenant
from app.models.integration import Integration
from app.core.encryption import get_credential
from app.workers.tasks.call_ingest import ingest_call
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_CACHE_TTL = 3600 * 4  # session-long recordings can run up to maxLength=3600s


def _cache_key(tenant_id: str, call_uuid: str) -> str:
    return f"haip:vobiz:call:{tenant_id}:{call_uuid}"


def _to_e164_in(number: str) -> str:
    """Normalize a domestic-format Indian number (e.g. "08071581336") to
    full E.164 ("+918071581336"). Vobiz's own DID/callerId records are
    E.164 -- posting back a domestic-format number as callerId fails their
    account-ownership check silently (CALL_REJECTED, no SIP code)."""
    number = (number or "").strip()
    if number.startswith("+"):
        return number
    return "+91" + number.lstrip("0")


def _resolve_tenant_and_creds(db: Session, tenant_slug: str, url_secret: str) -> tuple[Tenant, dict]:
    """
    Resolves tenant + validates the URL-path secret, and returns the tenant's
    own Vobiz credentials (auth_id/auth_token/forward_number) — this is the
    client's own Vobiz account, not a shared HAIP server credential, so it's
    stored per-tenant in the same encrypted Integration row the webhook
    secret comes from (api_key -> auth_id, api_secret -> auth_token).
    """
    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    integration = db.query(Integration).filter_by(tenant_id=tenant.id, kind="vobiz").first()
    if not integration or not integration.credentials_kms_blob:
        log.warning("vobiz_integration_not_configured", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Vobiz integration not configured for this tenant")

    blob = integration.credentials_kms_blob
    tenant_secret = get_credential(blob, "webhook_secret")
    if not tenant_secret or not secrets.compare_digest(url_secret, tenant_secret):
        log.warning("vobiz_url_secret_invalid", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    creds = {
        "auth_id": get_credential(blob, "api_key"),
        "auth_token": get_credential(blob, "api_secret"),
        "forward_number": get_credential(blob, "forward_number"),
    }
    return tenant, creds


@router.post("/vobiz/{tenant_slug}/{url_secret}/answer")
async def vobiz_answer_webhook(
    tenant_slug: str,
    url_secret: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Vobiz Answer URL — fires when an inbound call arrives. Caches From/To/
    Direction/started_at keyed by CallUUID, then replies with XML that
    records the whole session and dials the agent's forwarding number.
    """
    tenant, creds = _resolve_tenant_and_creds(db, tenant_slug, url_secret)
    form = await request.form()
    data = dict(form)

    call_uuid = data.get("CallUUID", "")
    if not call_uuid:
        log.warning("vobiz_answer_missing_call_uuid", tenant=tenant_slug)
        raise HTTPException(status_code=400, detail="Missing CallUUID")

    log.info("vobiz_answer_received", tenant=tenant_slug, call_uuid=call_uuid)

    set_cached(
        _cache_key(tenant.id, call_uuid),
        {
            "From": data.get("From", ""),
            "To": data.get("To", ""),
            "Direction": data.get("Direction", "inbound"),
            "started_at": data.get("StartTime", ""),
        },
        ttl=_CACHE_TTL,
    )

    forward_number = creds.get("forward_number")
    if not forward_number:
        log.error("vobiz_forward_number_not_configured", tenant=tenant_slug)
        return Response(
            content=(
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Response><Speak>Sorry, this line is not configured yet.</Speak><Hangup/></Response>'
            ),
            media_type="application/xml",
        )

    # request.base_url resolves to plain "http://" behind the reverse proxy --
    # Uvicorn doesn't trust X-Forwarded-Proto by default, so it ignores the
    # proxy's (correct) "https" and falls back to the raw ASGI connection
    # scheme. A callbackUrl handed to Vobiz over http:// against an
    # https-only domain means the recording-completion callback silently
    # never lands. Use settings.API_BASE_URL (already correct, same pattern
    # integrations.py's webhook-info endpoints use) instead.
    base = (settings.API_BASE_URL or str(request.base_url).rstrip("/")).rstrip("/")
    recording_callback_url = f"{base}/api/v1/webhooks/vobiz/{tenant_slug}/{url_secret}/recording"
    log.info(
        "vobiz_answer_xml_built",
        tenant=tenant_slug,
        call_uuid=call_uuid,
        request_base_url=str(request.base_url),
        callback_url=recording_callback_url,
        forwarded_proto=request.headers.get("x-forwarded-proto"),
        forwarded_host=request.headers.get("x-forwarded-host"),
        host_header=request.headers.get("host"),
    )
    # Vobiz's own docs (vobiz.ai/docs/call/transfer-call) show <Number> and
    # callerId in full "+"-prefixed E.164, and warn that callerId must be a
    # number "owned or authorized by your account" -- the raw "To" value
    # Vobiz posts back (e.g. "08071581336", domestic format, no country code)
    # doesn't match how the DID is registered on their side, so it was
    # silently failing account-ownership validation (CALL_REJECTED, no SIP
    # code, confirmed via the account's own CDR export).
    caller_id = _to_e164_in(data.get("To", ""))
    dial_number = forward_number if forward_number.startswith("+") else _to_e164_in(forward_number)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Record fileFormat="mp3" recordSession="true" maxLength="3600" '
        f'callbackUrl="{recording_callback_url}" redirect="false" playBeep="false"/>'
        f'<Dial callerId="{caller_id}" timeout="30" timeLimit="1800" redirect="false">'
        f"<Number>{dial_number}</Number>"
        "</Dial>"
        "<Hangup/>"
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/vobiz/{tenant_slug}/{url_secret}/recording")
async def vobiz_recording_webhook(
    tenant_slug: str,
    url_secret: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Vobiz recording callback — fires once the session recording finishes.
    Merges the cached call metadata from the answer webhook, then queues
    the same call_ingest pipeline every IVR provider uses.
    """
    tenant, creds = _resolve_tenant_and_creds(db, tenant_slug, url_secret)
    form = await request.form()
    data = dict(form)
    # Field names for the recording-completion callback aren't confirmed from
    # docs (their REST-triggered /Record/ endpoint uses different snake_case
    # names than the XML <Record> verb's Plivo-style PascalCase we assumed) --
    # log the raw payload once so we can see ground truth instead of guessing.
    log.info(
        "vobiz_recording_raw_payload",
        tenant=tenant_slug,
        raw_form=data,
        raw_query=dict(request.query_params),
    )

    call_uuid = data.get("CallUUID") or request.query_params.get("CallUUID", "")
    if not call_uuid:
        log.warning("vobiz_recording_missing_call_uuid", tenant=tenant_slug)
        return {"status": "ignored"}

    cached = get_cached(_cache_key(tenant.id, call_uuid)) or {}

    merged = {
        "CallUUID": call_uuid,
        "From": cached.get("From", ""),
        "To": cached.get("To", ""),
        "Direction": cached.get("Direction", "inbound"),
        "RecordUrl": data.get("RecordFile") or data.get("RecordUrl", ""),
        "RecordingDuration": data.get("RecordingDuration", "0"),
        "agent_number": creds.get("forward_number", ""),
        "started_at": cached.get("started_at", ""),
        "ended_at": data.get("RecordingEndMs", ""),
    }

    log.info("vobiz_recording_received", tenant=tenant_slug, call_uuid=call_uuid)
    # verify_webhook_signature() is a documented no-op for this provider (see
    # VobizAdapter) -- the URL-path secret checked above IS the auth. Passing
    # b"" avoids re-reading the request body, which request.form() above
    # already consumed (a second await request.body() raises "Stream consumed").
    adapter = get_ivr_adapter("vobiz")
    if not adapter.verify_webhook_signature(b"", dict(request.headers)):
        raise HTTPException(status_code=401, detail="Invalid signature")

    ingest_call.delay(payload=merged, tenant_id=tenant.id, ivr_provider="vobiz")
    return {"status": "queued"}
