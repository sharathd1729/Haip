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
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Request, HTTPException, Depends, Response, Query
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


def _dial_status_cache_key(tenant_id: str, call_uuid: str) -> str:
    return f"haip:vobiz:dialstatus:{tenant_id}:{call_uuid}"


def _to_e164_in(number: str) -> str:
    """Normalize a domestic-format Indian number (e.g. "08071581336") to
    full E.164 ("+918071581336"). Vobiz's own DID/callerId records are
    E.164 -- posting back a domestic-format number as callerId fails their
    account-ownership check silently (CALL_REJECTED, no SIP code)."""
    number = (number or "").strip()
    if not number.startswith("+"):
        number = "+91" + number.lstrip("0")

    # Defensive dedup: some guest phone numbers were saved with an accidental
    # double country-code prefix by an upstream ingestion bug (same shape as
    # McubeAdapter._normalize_phone's historical bug, fixed going forward but
    # never backfilled) -- "+91" followed by 12 digits that themselves start
    # with "91" is never a real Indian mobile number (those start 6/7/8/9),
    # only ever this bug's signature. Confirmed live: dialing the raw
    # (unrepaired) value gets instantly rejected by Vobiz (RecordingDurationMs
    # ~20 -- the call drops the moment the agent picks up).
    if number.startswith("+91"):
        local = number[3:]
        if len(local) == 12 and local.startswith("91"):
            number = "+91" + local[2:]

    return number


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
        "did_number": get_credential(blob, "did_number"),
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

    from app.services import ivr_routing_service

    forward_number = creds.get("forward_number")
    dial_numbers = ivr_routing_service.resolve_dial_numbers(
        db, tenant, fallback_number=forward_number, caller_number=data.get("From", ""),
    )
    if not dial_numbers:
        log.error("vobiz_no_dial_numbers_configured", tenant=tenant_slug)
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
    dial_status_callback_url = f"{base}/api/v1/webhooks/vobiz/{tenant_slug}/{url_secret}/dial-status"
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
    e164_numbers = [n if n.startswith("+") else _to_e164_in(n) for n in dial_numbers]

    # Outside business_hours: skip the Dial attempt entirely rather than
    # ringing agents who aren't expected to be working. No new audio slot
    # for this -- reuses the same voicemail prompt as the no-answer
    # fallback below (the caller doesn't need a different script for
    # "closed" vs "nobody picked up", and no separate script was given for
    # it). A tenant with no business_hours configured is always "open"
    # (is_within_business_hours's own fail-open default) so this is a
    # no-op for every tenant until they set hours.
    within_hours = ivr_routing_service.is_within_business_hours(tenant)

    # fixed_order rings candidates one at a time -- a <Dial> verb that goes
    # unanswered falls through to the next verb in the Response, so N
    # sequential single-Number <Dial>s is the standard idiom for "try A,
    # then B, then C" (as opposed to parallel/every other strategy's single
    # <Dial> with multiple <Number> children, which rings them all at once).
    # Per-leg timeout is shorter here so the total across every candidate
    # stays reasonable for the caller.
    # callbackUrl added on both branches: Vobiz's DialAnswer/DialConnected
    # events (with DialBLegTo -- the number that actually answered) and the
    # final DialStatus reach the new dial-status webhook, which caches the
    # resolved agent and the real answered/no-answer signal for
    # vobiz_recording_webhook to merge in. See ivr_routing_service /
    # call_ingest.py / call_status_service.py -- this is the one missing
    # piece both inbound agent attribution and accurate missed-call
    # detection depend on. UNCONFIRMED against real Vobiz behavior: the
    # exact DialAnswer/DialStatus field names (Vobiz's docs describe them,
    # but this hasn't been exercised against a real call yet) -- the new
    # webhook logs the full raw payload unconditionally specifically to
    # settle this on the first real call, same practice as
    # vobiz_recording_webhook's own "log raw payload, don't guess" comment.
    # Confirmed against vobiz.ai/docs/xml/dial (live fetch, not guessed):
    # DialAnswer/DialConnected/DialHangup (with DialBLegTo) go to
    # callbackUrl, but the terminal DialStatus result -- the signal this
    # whole missed-call-detection fix depends on -- goes to a SEPARATE
    # `action` attribute, not callbackUrl. Without `action` set, Vobiz
    # never sends DialStatus at all, which is exactly why ivr_dial_status
    # sat NULL on every single call after this shipped. redirect="false"
    # (already set below) is exactly right for `action` per the docs: "if
    # false, sends result but doesn't redirect" -- Vobiz posts DialStatus
    # then execution falls through to voicemail_xml/Hangup as intended,
    # rather than trying to execute whatever XML the action response
    # contains. Both attributes point at the same endpoint -- the handler
    # already reads whichever fields (DialBLegTo vs DialStatus) are present
    # in a given POST, so no handler change is needed.
    if not within_hours:
        dial_xml = ""
    elif ivr_routing_service.dial_mode(tenant) == "sequential" and len(e164_numbers) > 1:
        dial_xml = "".join(
            f'<Dial callerId="{caller_id}" timeout="20" timeLimit="1800" redirect="false" '
            f'callbackUrl="{dial_status_callback_url}" action="{dial_status_callback_url}">'
            f"<Number>{n}</Number></Dial>"
            for n in e164_numbers
        )
    else:
        number_tags = "".join(f"<Number>{n}</Number>" for n in e164_numbers)
        dial_xml = (
            f'<Dial callerId="{caller_id}" timeout="30" timeLimit="1800" redirect="false" '
            f'callbackUrl="{dial_status_callback_url}" action="{dial_status_callback_url}">'
            f"{number_tags}</Dial>"
        )

    # Plays before the Dial rather than as hold audio during it -- Vobiz's
    # XML dialect (Plivo-style) executes verbs sequentially, and a nested
    # "audio playing while ringing" isn't a documented <Dial> feature, so
    # sequential (greeting, then ring) is the reliable interpretation:
    # caller hears the greeting once, then normal ringback while the
    # agent(s) ring. Skipped outside business hours too -- the caller goes
    # straight to the voicemail prompt, no "please hold" before a call that
    # was never going to ring anyone.
    greeting_url = ivr_routing_service.resolve_greeting_url(tenant) if within_hours else None
    greeting_xml = f'<Play>{xml_escape(greeting_url)}</Play>' if greeting_url else ""

    # Plays after Dial falls through unanswered, or immediately (no Dial at
    # all) when outside business hours -- either way this is "no one's
    # coming to the phone." The whole-session <Record> above already
    # captures whatever the caller says after this plays, so the second
    # <Record> here exists only to give a beep + a window to speak, not
    # for its own completion callback (deliberately omitted -- reusing
    # recording_callback_url would risk that webhook firing twice for one
    # call, once for the real session recording and once for this tail).
    # UNCONFIRMED against real Vobiz behavior: whether a <Record> without
    # callbackUrl is accepted, and whether Dial-timeout fallthrough reaches
    # a non-Dial verb the same way it reaches a sequential Dial->Dial.
    # Worst case if either assumption is wrong: identical to today's
    # behavior (silent hangup) -- no regression, just no new behavior.
    voicemail_url = ivr_routing_service.resolve_voicemail_url(tenant)
    voicemail_xml = (
        f'<Play>{xml_escape(voicemail_url)}</Play>'
        f'<Record playBeep="true" maxLength="60" redirect="false"/>'
    ) if voicemail_url else ""

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Record fileFormat="mp3" recordSession="true" maxLength="3600" '
        f'callbackUrl="{recording_callback_url}" redirect="false" playBeep="false"/>'
        f"{greeting_xml}"
        f"{dial_xml}"
        f"{voicemail_xml}"
        "<Hangup/>"
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/vobiz/{tenant_slug}/{url_secret}/dial-status")
async def vobiz_dial_status_webhook(
    tenant_slug: str,
    url_secret: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Vobiz Dial callbackUrl -- fires multiple times during one <Dial> with
    real-time B-leg events (DialAnswer/DialConnected/DialHangup) plus a
    final DialStatus. Per Vobiz's docs: DialAnswer/DialConnected carry
    DialBLegTo (the number that actually answered) and DialBLegPosition
    (which of several parallel-rung numbers it was); the terminal event
    carries DialStatus (completed/busy/failed/cancel/timeout/no-answer).

    UNCONFIRMED against a real call yet -- logs the full raw payload
    unconditionally first so the exact field names are settled from ground
    truth, same practice as vobiz_recording_webhook's own comment. Never
    raises on an unexpected shape: this is a best-effort signal, and its
    total absence is exactly today's status quo (no attribution, duration-
    based missed-call guess) -- not a regression.
    """
    tenant, creds = _resolve_tenant_and_creds(db, tenant_slug, url_secret)
    form = await request.form()
    data = dict(form)

    log.info("vobiz_dial_status_raw_payload", tenant=tenant_slug, raw_form=data)

    call_uuid = data.get("CallUUID", "")
    if not call_uuid:
        return {"status": "ignored"}

    dial_b_leg_to = data.get("DialBLegTo", "")
    if dial_b_leg_to:
        try:
            from app.workers.tasks.call_ingest import cache_click_to_call_agent
            from app.models.user import User

            e164 = _to_e164_in(dial_b_leg_to)
            agent = (
                db.query(User)
                .filter(
                    User.tenant_id == tenant.id,
                    User.phone == e164,
                    User.is_active.is_(True),
                    User.is_deleted.is_(False),
                )
                .first()
            )
            if agent:
                # Reuses the exact cache function/key already built for
                # outbound click-to-call attribution -- same cache, same
                # TTL, read back by the same lookup at ingest time
                # (call_ingest.py), so inbound and outbound are symmetric.
                cache_click_to_call_agent(tenant.id, call_uuid, agent.id)
                log.info("vobiz_dial_answered_by", tenant=tenant_slug, call_uuid=call_uuid, agent_id=agent.id)
        except Exception as exc:
            log.warning("vobiz_dial_status_agent_lookup_failed", tenant=tenant_slug, error=str(exc))

    dial_status = data.get("DialStatus", "")
    if dial_status:
        set_cached(_dial_status_cache_key(tenant.id, call_uuid), dial_status, ttl=_CACHE_TTL)

    return {"status": "ok"}


@router.post("/vobiz/{tenant_slug}/{url_secret}/outbound-answer")
async def vobiz_outbound_answer_webhook(
    tenant_slug: str,
    url_secret: str,
    request: Request,
    guest_number: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    AnswerURL for the click-to-call leg (calls.py::click_to_call ->
    VobizAdapter.initiate_click_to_call). Vobiz dials the agent's forwarding
    number first; once they pick up, this fires and returns XML that
    records the bridged session and dials the guest as the second leg --
    same Record+Dial shape as the inbound answer webhook, just with the
    guest number coming from the query string (baked into the answer_url at
    call-initiation time) instead of the inbound payload's "To" field.
    """
    tenant, creds = _resolve_tenant_and_creds(db, tenant_slug, url_secret)
    form = await request.form()
    data = dict(form)

    call_uuid = data.get("CallUUID", "")
    if not call_uuid:
        log.warning("vobiz_outbound_answer_missing_call_uuid", tenant=tenant_slug)
        raise HTTPException(status_code=400, detail="Missing CallUUID")

    did_number = creds.get("did_number") or ""
    guest_e164 = _to_e164_in(guest_number)
    caller_id = did_number if did_number.startswith("+") else _to_e164_in(did_number) if did_number else guest_e164

    log.info("vobiz_outbound_answer_received", tenant=tenant_slug, call_uuid=call_uuid, guest_number=guest_e164)

    set_cached(
        _cache_key(tenant.id, call_uuid),
        {
            "From": did_number,
            "To": guest_e164,
            "Direction": "outbound",
            "started_at": data.get("StartTime", ""),
        },
        ttl=_CACHE_TTL,
    )

    base = (settings.API_BASE_URL or str(request.base_url).rstrip("/")).rstrip("/")
    recording_callback_url = f"{base}/api/v1/webhooks/vobiz/{tenant_slug}/{url_secret}/recording"

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Record fileFormat="mp3" recordSession="true" maxLength="3600" '
        f'callbackUrl="{recording_callback_url}" redirect="false" playBeep="false"/>'
        f'<Dial callerId="{caller_id}" timeout="30" timeLimit="1800" redirect="false">'
        f"<Number>{guest_e164}</Number>"
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
        "ivr_dial_status": get_cached(_dial_status_cache_key(tenant.id, call_uuid)) or "",
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
