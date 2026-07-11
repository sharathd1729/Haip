import uuid
import os
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.core.config import settings
from app.core.encryption import encrypt_credentials, decrypt_credentials, get_credential
from app.core.security import create_access_token, decode_token
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.integration import Integration
from app.schemas.integration import IntegrationOut, IntegrationConnectRequest, IntegrationHealthResponse

router = APIRouter(prefix="/integrations", tags=["integrations"])

# ─── Catalog ─────────────────────────────────────────────────────────────────

CATALOG = [
    {
        "provider": "whatsapp_meta",
        "name": "WhatsApp Business",
        "description": "Connect your WhatsApp Cloud API account. Paste your Phone Number ID, WABA ID, and permanent access token from your Meta Business dashboard.",
        "category": "messaging",
        "auth_type": "manual",
        "logo": "whatsapp",
        "popular": True,
        "notes": "Get your credentials from Meta Business Suite → WhatsApp Manager → API Setup. Use a System User token (never expires) instead of a temporary token.",
    },
    {
        "provider": "instagram",
        "name": "Instagram DMs",
        "description": "Connect your Instagram Business Account using your Graph API access token to manage DMs and route leads into the pipeline.",
        "category": "messaging",
        "auth_type": "manual",
        "logo": "instagram",
        "popular": True,
        "notes": "Get your credentials from Meta Business Suite → Instagram → Settings → API Access. Requires instagram_manage_messages and pages_manage_metadata permissions.",
    },
    {
        "provider": "retalwise",
        "name": "RentalWise",
        "description": "Connect RentalWise channel manager / PMS to sync property availability, reservations, and guest folios directly into HAIP. Enables two-way rate updates and automated booking confirmations.",
        "category": "pms",
        "auth_type": "basic_auth",
        "logo": "hotel",
        "popular": True,
        "notes": "Your username, password, and API base URL are provided by your RentalWise Engagement Manager during onboarding. Contact support@rentalwise.com if you haven't received them.",
    },
    {
        "provider": "hostaway",
        "name": "Hostaway",
        "description": "Sync listings, reservations, and guest data from Hostaway. Auto-create inquiries on new bookings and push AI summaries back as reservation notes.",
        "category": "pms",
        "auth_type": "oauth2",
        "logo": "hotel",
        "popular": True,
        "notes": "You need your Hostaway Account ID and API Secret from Settings → API Access in Hostaway.",
    },
    {
        "provider": "staah",
        "name": "STAAH",
        "description": "Channel manager integration — pull availability, rates, and booking data for real-time sync with HAIP's CRM pipeline.",
        "category": "pms",
        "auth_type": "api_key",
        "logo": "hotel",
        "popular": False,
    },
    {
        "provider": "cloudbeds",
        "name": "Cloudbeds",
        "description": "Full PMS integration with Cloudbeds. Sync guests, reservations, and revenue data for unified reporting and AI concierge context.",
        "category": "pms",
        "auth_type": "api_key",
        "logo": "hotel",
        "popular": False,
        "notes": "Generate an API key from Cloudbeds → Settings → API Keys.",
    },
    {
        "provider": "haip_ivr",
        "name": "HAIP IVR",
        "description": "Built-in IVR — connect your Vobiz SIP number, configure a DTMF menu, and route calls to your team via Dograh AI.",
        "category": "telephony",
        "auth_type": "ivr_settings",
        "logo": "phone",
        "popular": True,
    },
    {
        "provider": "callerdesk",
        "name": "CallerDesk",
        "description": "Receive inbound call webhooks, trigger outbound calls, and pull recordings for AI analysis.",
        "category": "telephony",
        "auth_type": "api_key",
        "logo": "phone",
        "popular": True,
        "notes": "Whitelist your HAIP server IP in the CallerDesk portal before connecting.",
    },
    {
        "provider": "acefone",
        "name": "Acefone",
        "description": "Cloud telephony integration — inbound/outbound call routing, IVR, and recording retrieval.",
        "category": "telephony",
        "auth_type": "api_key",
        "logo": "phone",
        "popular": False,
    },
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _upsert_integration(db: Session, tenant_id: str, kind: str) -> Integration:
    row = db.query(Integration).filter_by(tenant_id=tenant_id, kind=kind).first()
    if not row:
        row = Integration(id=str(uuid.uuid4()), tenant_id=tenant_id, kind=kind)
        db.add(row)
    return row


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Catalog ─────────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_catalog():
    return CATALOG


# ─── List connected integrations ─────────────────────────────────────────────

@router.get("", response_model=List[IntegrationOut])
def list_integrations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(Integration).filter_by(tenant_id=current_user.tenant_id).all()
    catalog_map = {c["provider"]: c for c in CATALOG}
    result = []
    for row in rows:
        cat = catalog_map.get(row.kind, {})
        # Build safe metadata (never expose credentials)
        creds = decrypt_credentials(row.credentials_kms_blob) if row.credentials_kms_blob else {}
        safe_meta = {**( row.config or {})}
        if creds.get("api_key"):
            k = creds["api_key"]
            safe_meta["api_key_preview"] = k[:6] + "…" + k[-4:] if len(k) > 10 else "****"
        if creds.get("phone_number_id"):
            safe_meta["phone_number_id"] = creds["phone_number_id"]
        if creds.get("waba_id"):
            safe_meta["waba_id"] = creds["waba_id"]

        result.append(IntegrationOut(
            id=row.id,
            tenant_id=row.tenant_id,
            kind=row.kind,
            status=row.status or "disconnected",
            config={
                **safe_meta,
                # Embed catalog metadata so the frontend can display it
                "provider_name": cat.get("name"),
                "provider_description": cat.get("description"),
                "provider_category": cat.get("category"),
                "provider_auth_type": cat.get("auth_type"),
                "provider_logo": cat.get("logo"),
                "last_error": (row.config or {}).get("last_error"),
            },
            installed_at=row.installed_at,
            last_health_at=row.last_health_at,
        ))
    return result


# ─── WhatsApp Cloud API — manual credentials ──────────────────────────────────

@router.post("/whatsapp_meta/connect-key")
def connect_whatsapp_manual(
    body: dict,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """
    Client provides their own WhatsApp Cloud API credentials:
      phone_number_id   — from Meta Business → WhatsApp Manager → API Setup
      waba_id           — WhatsApp Business Account ID
      access_token      — Permanent System User token (never expires)
      app_secret        — optional, used to verify incoming webhook signatures
    """
    phone_number_id = (body.get("phone_number_id") or "").strip()
    waba_id = (body.get("waba_id") or "").strip()
    access_token = (body.get("access_token") or "").strip()
    app_secret = (body.get("app_secret") or "").strip()

    if not phone_number_id:
        raise HTTPException(status_code=400, detail="phone_number_id is required")
    if not access_token:
        raise HTTPException(status_code=400, detail="access_token is required")

    # Soft validation — try to verify token with Meta, but don't block save on failure.
    # Users can use "Test Connection" after saving to confirm credentials are working.
    display_phone = ""
    verified_name = ""
    validation_warning = None
    try:
        resp = httpx.get(
            f"https://graph.facebook.com/v20.0/{phone_number_id}",
            params={"access_token": access_token, "fields": "display_phone_number,verified_name"},
            timeout=10,
        )
        data = resp.json()
        if "error" in data:
            err_meta = data["error"]
            code = err_meta.get("code", 0)
            msg = err_meta.get("message", "Token rejected by Meta")
            if code in (190, 102):
                validation_warning = "Token could not be verified with Meta — it may be expired. Use 'Test Connection' to confirm after saving."
            elif code == 200:
                validation_warning = "Token may be missing permissions (whatsapp_business_messaging / whatsapp_business_management). Credentials saved — use 'Test Connection' to verify."
            elif code == 100:
                validation_warning = "Phone Number ID may be incorrect. Credentials saved — use 'Test Connection' to confirm."
            else:
                validation_warning = f"Meta returned: {msg}. Credentials saved — use 'Test Connection' to verify."
        else:
            display_phone = data.get("display_phone_number", "")
            verified_name = data.get("verified_name", "")
    except Exception:
        validation_warning = "Could not reach Meta API to validate — credentials saved. Use 'Test Connection' once network is available."

    row = _upsert_integration(db, current_user.tenant_id, "whatsapp_meta")
    row.credentials_kms_blob = encrypt_credentials({
        "access_token": access_token,
        "app_secret": app_secret,
        "phone_number_id": phone_number_id,
        "waba_id": waba_id,
    })
    row.config = {
        "phone_number_id": phone_number_id,
        "waba_id": waba_id,
        "display_phone": display_phone,
        "verified_name": verified_name,
    }
    row.status = "active"
    row.installed_at = _now()
    db.commit()
    return {
        "status": "connected",
        "phone_number_id": phone_number_id,
        "waba_id": waba_id,
        "display_phone": display_phone,
        "verified_name": verified_name,
        "warning": validation_warning,
    }


@router.get("/whatsapp_meta/webhook-info")
def get_whatsapp_webhook_info(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Return the webhook URL and verify token to paste into the client's Meta App."""
    base = (settings.API_BASE_URL or str(request.base_url).rstrip("/")).rstrip("/")
    # Force HTTPS for publicly displayed URLs
    base = base.replace("http://", "https://", 1) if base.startswith("http://") else base
    verify_token = settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN or "⚠ META_WEBHOOK_VERIFY_TOKEN not set"
    return {
        "webhook_url": f"{base}/api/v1/webhooks/whatsapp",
        "verify_token": verify_token,
        "instructions": [
            "Go to Meta Business Suite → Your App → WhatsApp → Configuration → Webhooks",
            "Click 'Edit' and paste the Webhook URL above",
            f"Enter Verify Token: {verify_token}",
            "Subscribe to: messages, message_deliveries, message_reads",
            "Click Verify and Save",
        ],
    }


# ─── Instagram Graph API — manual credentials ─────────────────────────────────

@router.post("/instagram/connect-key")
def connect_instagram_manual(
    body: dict,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """
    Client provides their own Instagram Graph API credentials:
      instagram_business_account_id  — IG Business Account ID
      access_token                   — Page access token with instagram_manage_messages
      app_secret                     — optional, for webhook signature verification
    """
    ig_account_id = (body.get("instagram_business_account_id") or "").strip()
    access_token = (body.get("access_token") or "").strip()
    app_secret = (body.get("app_secret") or "").strip()

    if not ig_account_id:
        raise HTTPException(status_code=400, detail="instagram_business_account_id is required")
    if not access_token:
        raise HTTPException(status_code=400, detail="access_token is required")

    # Quick validation — fetch IG account name
    ig_username = ""
    try:
        resp = httpx.get(
            f"https://graph.facebook.com/v20.0/{ig_account_id}",
            params={"access_token": access_token, "fields": "username,name"},
            timeout=10,
        )
        data = resp.json()
        if "error" in data:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid credentials: {data['error'].get('message', 'Token rejected by Meta')}"
            )
        ig_username = data.get("username", data.get("name", ""))
    except HTTPException:
        raise
    except Exception:
        ig_username = ""

    row = _upsert_integration(db, current_user.tenant_id, "instagram")
    row.credentials_kms_blob = encrypt_credentials({
        "access_token": access_token,
        "app_secret": app_secret,
        "instagram_business_account_id": ig_account_id,
    })
    row.config = {
        "instagram_business_account_id": ig_account_id,
        "username": ig_username,
    }
    row.status = "active"
    row.installed_at = _now()
    db.commit()
    return {
        "status": "connected",
        "instagram_business_account_id": ig_account_id,
        "username": ig_username,
    }


@router.get("/instagram/oauth-start")
def start_instagram_oauth(token: str, db: Session = Depends(get_db)):
    """
    Redirects to Meta's Instagram Business Login consent screen.
    Meta redirects back to /instagram/oauth-callback with a `code`,
    which is exchanged server-side for a properly-scoped access token —
    no manual curl/copy-paste required.

    Accepts the HAIP JWT as a `?token=` query param (not an Authorization
    header) since this is opened as a plain browser link, not an API call.
    """
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    current_user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False, is_active=True).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")
    if current_user.role.value not in (UserRole.OWNER.value, UserRole.MANAGER.value):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if not settings.INSTAGRAM_APP_ID:
        raise HTTPException(status_code=500, detail="INSTAGRAM_APP_ID not configured")

    state = create_access_token(
        {"tenant_id": current_user.tenant_id, "purpose": "ig_oauth"},
        expires_delta=timedelta(minutes=10),
    )
    base = (settings.API_BASE_URL or "").rstrip("/")
    redirect_uri = f"{base}/api/v1/integrations/instagram/oauth-callback"
    scope = ",".join([
        "instagram_business_basic",
        "instagram_business_manage_messages",
        "instagram_business_manage_comments",
        "instagram_business_content_publish",
        "instagram_business_manage_insights",
    ])
    auth_url = (
        "https://www.instagram.com/oauth/authorize"
        f"?force_reauth=true&client_id={settings.INSTAGRAM_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code&scope={scope}&state={state}"
    )
    return RedirectResponse(auth_url)


@router.get("/instagram/oauth-callback")
def instagram_oauth_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    """Public callback — Meta redirects here after the user authorizes."""
    if error:
        return HTMLResponse(f"<h3>Instagram authorization failed: {error}</h3>", status_code=400)

    decoded = decode_token(state)
    if not decoded or decoded.get("purpose") != "ig_oauth":
        return HTMLResponse("<h3>Invalid or expired authorization state. Please retry.</h3>", status_code=400)
    tenant_id = decoded["tenant_id"]

    row = db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram").first()
    existing_creds = decrypt_credentials(row.credentials_kms_blob) if row and row.credentials_kms_blob else {}
    app_secret = existing_creds.get("app_secret", "")
    if not app_secret:
        return HTMLResponse(
            "<h3>No Instagram App Secret saved yet for this workspace. "
            "Save one via the manual connect form first, then retry.</h3>",
            status_code=400,
        )

    base = (settings.API_BASE_URL or "").rstrip("/")
    redirect_uri = f"{base}/api/v1/integrations/instagram/oauth-callback"

    try:
        short_resp = httpx.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": settings.INSTAGRAM_APP_ID,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=15,
        )
        short_data = short_resp.json()
        if "access_token" not in short_data:
            return HTMLResponse(
                f"<h3>Token exchange failed: {short_data}</h3>"
                f"<p>redirect_uri sent: {redirect_uri}</p>"
                f"<p>client_id sent: {settings.INSTAGRAM_APP_ID}</p>"
                f"<p>code length: {len(code)}</p>",
                status_code=400,
            )

        long_resp = httpx.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret,
                "access_token": short_data["access_token"],
            },
            timeout=15,
        )
        long_data = long_resp.json()
        access_token = long_data.get("access_token", short_data["access_token"])

        me_resp = httpx.get(
            "https://graph.instagram.com/me",
            params={"fields": "user_id,username", "access_token": access_token},
            timeout=15,
        )
        me_data = me_resp.json()
        ig_account_id = str(me_data.get("user_id", ""))
        username = me_data.get("username", "")
    except Exception as exc:
        return HTMLResponse(f"<h3>Instagram OAuth exchange error: {exc}</h3>", status_code=500)

    row = _upsert_integration(db, tenant_id, "instagram")
    row.credentials_kms_blob = encrypt_credentials({
        "access_token": access_token,
        "app_secret": app_secret,
        "instagram_business_account_id": ig_account_id,
    })
    row.config = {
        "instagram_business_account_id": ig_account_id,
        "username": username,
    }
    row.status = "active"
    row.installed_at = _now()
    db.commit()

    return HTMLResponse(
        f"<h3>Instagram connected: @{username or ig_account_id}</h3>"
        "<p>You can close this tab and return to HAIP.</p>"
    )


@router.get("/instagram/webhook-info")
def get_instagram_webhook_info(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    base = (settings.API_BASE_URL or str(request.base_url).rstrip("/")).rstrip("/")
    # Force HTTPS for publicly displayed URLs
    base = base.replace("http://", "https://", 1) if base.startswith("http://") else base
    verify_token = settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN or "⚠ META_WEBHOOK_VERIFY_TOKEN not set"
    return {
        "webhook_url": f"{base}/api/v1/webhooks/instagram",
        "verify_token": verify_token,
        "instructions": [
            "Go to Meta Business Suite → Your App → Webhooks → instagram",
            "Paste the Webhook URL above",
            f"Enter Verify Token: {verify_token}",
            "Subscribe to: messages",
            "Click Verify and Save",
        ],
    }


# ─── Retalwise ───────────────────────────────────────────────────────────────

@router.get("/retalwise/credentials")
def get_retalwise_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Server-to-server credential retrieval used by the Next.js proxy layer
    (src/app/api/rentalwise/_helpers.ts).

    Returns the decrypted RentalWise credentials so the Next.js API routes
    can make authenticated calls to the RentalWise API on behalf of the tenant.

    ⚠ Never call this endpoint from client-side (browser) code — it is only
    intended for server-side Next.js API routes where the response is never
    forwarded to the browser.
    """
    # Accept both "retalwise" (legacy typo) and "rentalwise"
    row = (
        db.query(Integration)
        .filter(
            Integration.tenant_id == current_user.tenant_id,
            Integration.kind.in_(["retalwise", "rentalwise"]),
        )
        .first()
    )

    if not row or row.status != "active":
        raise HTTPException(status_code=404, detail="RentalWise integration not connected")

    creds = decrypt_credentials(row.credentials_kms_blob) if row.credentials_kms_blob else {}
    cfg   = row.config or {}

    return {
        "api_token": creds.get("api_token") or None,
        "username":  creds.get("username")  or None,
        "password":  creds.get("password")  or None,
        "base_url":  cfg.get("base_url", "https://app.rentalwise.io"),
    }


@router.post("/retalwise/connect-key")
def connect_retalwise(
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """
    RentalWise supports two auth modes:
      1. Bearer token (preferred): { "api_token": "14079|rw_production_..." }
      2. Basic auth (legacy):       { "username": "...", "password": "..." }
    Optional: { "base_url": "https://partners-api.rentalwise.com" }
    """
    # Prefer api_token (Bearer); fall back to username/password (Basic)
    api_token = (body.get("api_token") or "").strip()
    username  = (body.get("username") or body.get("api_key") or "").strip()
    password  = (body.get("password") or body.get("api_secret") or "").strip()
    base_url  = (body.get("base_url") or "").strip()

    # Validate base_url is actually a URL (not accidentally an API token)
    if base_url and not base_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail=(
                "API Base URL must start with https:// (e.g. https://partners-api.rentalwise.com). "
                "Leave it blank to use the default production URL. "
                "If you have an API token, paste it into the 'API Token' field instead."
            ),
        )

    if not api_token and not username:
        raise HTTPException(status_code=400, detail="Either an API token or a username is required")
    if not api_token and not password:
        raise HTTPException(status_code=400, detail="password is required when using username/password auth")

    # Soft ping — save credentials regardless; user can Test Connection afterward
    ping_warning = None
    try:
        from app.adapters.pms.retalwise import RentalwiseAdapter
        adapter = RentalwiseAdapter(
            api_token=api_token,
            username=username,
            password=password,
            base_url=base_url or "https://app.rentalwise.io",
        )
        if not adapter.ping():
            ping_warning = "Could not reach RentalWise API — credentials saved. Use 'Test Connection' to verify once the API is accessible."
    except Exception:
        ping_warning = "RentalWise API unreachable — credentials saved. Use 'Test Connection' to verify."

    # Guard: give a clear 503 if ENCRYPTION_KEY is not configured, rather than a bare 500
    try:
        creds_blob = encrypt_credentials(
            {"api_token": api_token} if api_token else {"username": username, "password": password}
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Server configuration error: ENCRYPTION_KEY is not set. Contact your administrator.",
        ) from exc

    row = _upsert_integration(db, current_user.tenant_id, "retalwise")
    row.credentials_kms_blob = creds_blob
    row.config = {
        "base_url": base_url or "https://app.rentalwise.io",
        "auth_mode": "bearer" if api_token else "basic",
        "sync_properties": True,
        "sync_reservations": True,
        "sync_guests": True,
    }
    row.status = "active"
    row.installed_at = _now()
    db.commit()

    # Trigger initial sync in background
    try:
        from app.workers.tasks.sync_retalwise import sync_retalwise
        background_tasks.add_task(lambda: sync_retalwise.delay(current_user.tenant_id))
    except Exception:
        pass  # Celery not running — sync will happen on next beat tick

    return {"status": "connected", "provider": "retalwise", "warning": ping_warning}


# ─── Hostaway OAuth2 ─────────────────────────────────────────────────────────

@router.post("/hostaway/connect-key")
def connect_hostaway(
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    account_id = (body.get("account_id") or body.get("api_key") or "").strip()
    api_secret = (body.get("api_secret") or "").strip()
    if not account_id or not api_secret:
        raise HTTPException(status_code=400, detail="account_id and api_secret are required")

    row = _upsert_integration(db, current_user.tenant_id, "hostaway")
    row.credentials_kms_blob = encrypt_credentials({
        "account_id": account_id,
        "api_secret": api_secret,
    })
    row.config = {"sync_listings": True, "sync_reservations": True}
    row.status = "active"
    row.installed_at = _now()
    db.commit()

    from app.workers.tasks.sync_hostaway import sync_hostaway
    background_tasks.add_task(
        lambda: sync_hostaway.delay(current_user.tenant_id)
    )

    return {"status": "connected", "provider": "hostaway"}


# ─── Generic API-Key connect (fallback — keep AFTER all specific routes) ──────

@router.post("/{kind}/connect-key")
def connect_via_api_key(
    kind: str,
    body: dict,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """
    Fallback handler for providers that only need a single API key (CallerDesk, Acefone, STAAH, Cloudbeds).
    For IVR providers (callerdesk, acefone), webhook_secret is required to enable per-tenant
    webhook signature verification. Set the same value in the provider's dashboard → Webhooks → Secret.
    """
    api_key = (body.get("api_key") or "").strip()
    api_secret = (body.get("api_secret") or "").strip()
    webhook_secret = (body.get("webhook_secret") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")

    _IVR_KINDS = {"callerdesk", "acefone"}
    if kind in _IVR_KINDS and not webhook_secret:
        raise HTTPException(
            status_code=400,
            detail=(
                f"webhook_secret is required for {kind}. "
                "Generate any random string, set it here, and paste the same value into "
                f"the {kind.title()} dashboard → Webhooks → Secret."
            ),
        )

    row = _upsert_integration(db, current_user.tenant_id, kind)
    creds: dict = {"api_key": api_key}
    if api_secret:
        creds["api_secret"] = api_secret
    if webhook_secret:
        creds["webhook_secret"] = webhook_secret
    row.credentials_kms_blob = encrypt_credentials(creds)
    row.status = "active"
    row.installed_at = _now()
    db.commit()
    return {"status": "connected", "provider": kind}


# ─── Manual sync trigger ─────────────────────────────────────────────────────

@router.post("/{kind}/sync")
def trigger_sync(
    kind: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    row = db.query(Integration).filter_by(tenant_id=current_user.tenant_id, kind=kind).first()
    if not row or row.status != "active":
        raise HTTPException(status_code=404, detail="Integration not connected")

    if kind == "retalwise":
        try:
            # Try Celery first; fall back to direct execution if worker not running
            from app.workers.tasks.sync_retalwise import sync_retalwise
            sync_retalwise.delay(current_user.tenant_id)
        except Exception:
            from app.workers.tasks.sync_retalwise import sync_retalwise
            sync_retalwise(current_user.tenant_id)
    elif kind == "hostaway":
        from app.workers.tasks.sync_hostaway import sync_hostaway
        sync_hostaway.delay(current_user.tenant_id)
    else:
        raise HTTPException(status_code=400, detail=f"No sync task for {kind}")

    return {"status": "sync_queued", "provider": kind}


# ─── Disconnect / Verify ─────────────────────────────────────────────────────

@router.delete("/{kind}")
def disconnect_integration(
    kind: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    row = db.query(Integration).filter_by(tenant_id=current_user.tenant_id, kind=kind).first()
    if not row:
        raise HTTPException(status_code=404, detail="Integration not found")
    row.status = "disconnected"
    row.credentials_kms_blob = None
    row.config = {}
    db.commit()
    return {"status": "disconnected"}


@router.post("/{kind}/verify")
def verify_integration(
    kind: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(Integration).filter_by(tenant_id=current_user.tenant_id, kind=kind).first()
    if not row or row.status != "active":
        raise HTTPException(status_code=404, detail="Integration not connected")
    row.last_health_at = _now()
    db.commit()
    return {"status": "ok", "last_verified": row.last_health_at}


# ─── Legacy endpoints (kept for backward compat) ─────────────────────────────

@router.post("/{kind}/connect", response_model=IntegrationOut)
def connect_integration(
    kind: str,
    body: IntegrationConnectRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    row = _upsert_integration(db, current_user.tenant_id, kind)
    creds = {**(body.config or {}), **body.credentials}
    row.credentials_kms_blob = encrypt_credentials(creds)
    row.status = "active"
    row.installed_at = _now()
    db.commit()
    db.refresh(row)
    return row


@router.get("/meta/quality")
def get_meta_quality(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    S7 — Return the last `days` of Meta WABA quality snapshots for the tenant.
    Frontend uses these to render the quality trend chart.
    """
    from app.workers.tasks.meta_quality_poll import MetaQualitySnapshot
    from datetime import timedelta
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    snapshots = (
        db.query(MetaQualitySnapshot)
        .filter_by(tenant_id=current_user.tenant_id)
        .filter(MetaQualitySnapshot.created_at >= cutoff)
        .order_by(MetaQualitySnapshot.created_at.asc())
        .limit(720)  # 30 days × 24h = 720 hourly snapshots max
        .all()
    )

    # Latest snapshot = current state
    latest = snapshots[-1] if snapshots else None

    return {
        "current": {
            "quality_rating": latest.quality_rating if latest else None,
            "messaging_limit_tier": latest.messaging_limit_tier if latest else None,
            "polled_at": latest.created_at.isoformat() if latest and latest.created_at else None,
        },
        "snapshots": [
            {
                "ts": s.created_at.isoformat() if s.created_at else None,
                "quality_rating": s.quality_rating,
                "messaging_limit_tier": s.messaging_limit_tier,
            }
            for s in snapshots
        ],
    }


@router.post("/{kind}/test", response_model=IntegrationHealthResponse)
def test_integration(
    kind: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    O6 — Perform a live round-trip to verify the integration is working.
    Returns diagnostic message if it fails.
    Cached: updates last_health_at; caller should debounce on frontend (60s).
    """
    row = db.query(Integration).filter_by(tenant_id=current_user.tenant_id, kind=kind).first()
    if not row:
        return IntegrationHealthResponse(kind=kind, status="not_configured", message="Integration not configured yet.")

    creds = decrypt_credentials(row.credentials_kms_blob) if row.credentials_kms_blob else {}

    status = "active"
    message = "Connection verified successfully."

    try:
        if kind == "whatsapp_meta":
            # Call GET /{phone_number_id} on Graph API
            phone_number_id = creds.get("phone_number_id", "")
            access_token = creds.get("access_token", "")
            if not phone_number_id or not access_token:
                status = "error"
                message = "Missing phone_number_id or access_token in credentials."
            else:
                resp = httpx.get(
                    f"https://graph.facebook.com/v19.0/{phone_number_id}",
                    params={"access_token": access_token},
                    timeout=8,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    display_name = data.get("display_phone_number", phone_number_id)
                    message = f"Connected: {display_name}"
                elif resp.status_code == 401:
                    status = "error"
                    message = "Token expired or invalid. Please reconnect with a fresh System User token."
                else:
                    status = "error"
                    err = resp.json().get("error", {})
                    message = f"Meta API error: {err.get('message', resp.text[:120])}"

        elif kind == "instagram":
            access_token = creds.get("access_token", "")
            ig_account_id = creds.get("instagram_business_account_id", "")
            if not access_token or not ig_account_id:
                status = "error"
                message = "Missing instagram_business_account_id or access_token."
            else:
                resp = httpx.get(
                    f"https://graph.facebook.com/v19.0/{ig_account_id}",
                    params={"fields": "id,name", "access_token": access_token},
                    timeout=8,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    message = f"Connected: {data.get('name', ig_account_id)}"
                elif resp.status_code == 401:
                    status = "error"
                    message = "Token expired or revoked. Please reconnect Instagram."
                else:
                    status = "error"
                    message = f"Instagram API error ({resp.status_code})"

        elif kind in ("callerdesk", "acefone"):
            # For IVR: call the provider's health/account endpoint
            api_key = creds.get("api_key", "")
            if not api_key:
                status = "error"
                message = "Missing api_key in credentials."
            else:
                if kind == "callerdesk":
                    resp = httpx.get(
                        "https://api.callerdesk.io/v1/account",
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=8,
                    )
                else:
                    resp = httpx.get(
                        "https://api.acefone.in/v1/account/details",
                        headers={"X-API-Key": api_key},
                        timeout=8,
                    )
                if resp.status_code == 200:
                    message = f"{kind.title()} account verified."
                elif resp.status_code in (401, 403):
                    status = "error"
                    message = "Invalid API key. Please check your credentials."
                else:
                    status = "error"
                    message = f"{kind.title()} API error ({resp.status_code})."

        else:
            # Generic: just mark health timestamp and return ok
            message = f"{kind} connection appears configured. No active test available."

    except httpx.TimeoutException:
        status = "error"
        message = "Connection timed out. Check your credentials or try again."
    except Exception as exc:
        status = "error"
        message = f"Unexpected error: {str(exc)[:120]}"

    # Persist test result — error_message is stored in config dict (no dedicated column)
    row.last_health_at = _now()
    row.status = status  # type: ignore[assignment]
    cfg = dict(row.config or {})
    if status == "error":
        cfg["last_error"] = message
    else:
        cfg.pop("last_error", None)
    row.config = cfg
    db.commit()

    return IntegrationHealthResponse(kind=kind, status=status, message=message)
