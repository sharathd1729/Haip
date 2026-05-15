import uuid
import os
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.core.encryption import encrypt_credentials, decrypt_credentials, get_credential
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
            organization_id=row.tenant_id,
            provider=row.kind,
            status=row.status or "disconnected",
            metadata_json=safe_meta,
            last_synced_at=row.last_health_at,
            error_message=None,
            token_expiry=None,
            created_at=row.created_at or "",
            updated_at=row.updated_at or "",
            provider_name=cat.get("name"),
            provider_description=cat.get("description"),
            provider_category=cat.get("category"),
            provider_auth_type=cat.get("auth_type"),
            provider_logo=cat.get("logo"),
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

    # Quick validation — call Graph API to check token is valid
    try:
        resp = httpx.get(
            f"https://graph.facebook.com/v20.0/{phone_number_id}",
            params={"access_token": access_token, "fields": "display_phone_number,verified_name"},
            timeout=10,
        )
        data = resp.json()
        if "error" in data:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid credentials: {data['error'].get('message', 'Token rejected by Meta')}"
            )
        display_phone = data.get("display_phone_number", "")
        verified_name = data.get("verified_name", "")
    except HTTPException:
        raise
    except Exception:
        # Validation failed — save anyway (offline / rate-limited)
        display_phone = ""
        verified_name = ""

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
    }


@router.get("/whatsapp_meta/webhook-info")
def get_whatsapp_webhook_info(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Return the webhook URL and verify token to paste into the client's Meta App."""
    base = str(request.base_url).rstrip("/")
    verify_token = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "haip-webhook-verify-token")
    return {
        "webhook_url": f"{base}/webhooks/whatsapp",
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


@router.get("/instagram/webhook-info")
def get_instagram_webhook_info(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    base = str(request.base_url).rstrip("/")
    verify_token = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "haip-webhook-verify-token")
    return {
        "webhook_url": f"{base}/webhooks/instagram",
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

@router.post("/retalwise/connect-key")
def connect_retalwise(
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """
    RentalWise uses HTTP Basic Auth.
    Pass: { "username": "...", "password": "...", "base_url": "https://..." }
    Legacy single api_key also accepted for backward compat.
    """
    username = (body.get("username") or body.get("api_key") or "").strip()
    password = (body.get("password") or body.get("api_secret") or "").strip()
    base_url = (body.get("base_url") or "").strip()

    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if not password:
        raise HTTPException(status_code=400, detail="password is required")

    # Verify credentials before saving
    from app.adapters.pms.retalwise import RentalwiseAdapter
    adapter = RentalwiseAdapter(
        username=username,
        password=password,
        base_url=base_url or "https://partners-api.rentalwise.com",
    )
    if not adapter.ping():
        raise HTTPException(
            status_code=400,
            detail="Could not connect to RentalWise — check your username, password, and base URL."
        )

    row = _upsert_integration(db, current_user.tenant_id, "retalwise")
    row.credentials_kms_blob = encrypt_credentials({"username": username, "password": password})
    row.config = {
        "base_url": base_url or "https://partners-api.rentalwise.com",
        "sync_properties": True,
        "sync_reservations": True,
        "sync_guests": True,
    }
    row.status = "active"
    row.installed_at = _now()
    db.commit()

    # Trigger initial sync in background
    from app.workers.tasks.sync_retalwise import sync_retalwise
    background_tasks.add_task(lambda: sync_retalwise.delay(current_user.tenant_id))

    return {"status": "connected", "provider": "retalwise"}


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
    """Fallback handler for providers that only need a single API key (CallerDesk, Acefone, STAAH, Cloudbeds)."""
    api_key = (body.get("api_key") or "").strip()
    api_secret = (body.get("api_secret") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")

    row = _upsert_integration(db, current_user.tenant_id, kind)
    creds: dict = {"api_key": api_key}
    if api_secret:
        creds["api_secret"] = api_secret
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
        from app.workers.tasks.sync_retalwise import sync_retalwise
        sync_retalwise.delay(current_user.tenant_id)
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
    row.status = "inactive"
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


@router.post("/{kind}/test", response_model=IntegrationHealthResponse)
def test_integration(
    kind: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(Integration).filter_by(tenant_id=current_user.tenant_id, kind=kind).first()
    if not row:
        return IntegrationHealthResponse(kind=kind, status="not_configured")
    row.last_health_at = _now()
    db.commit()
    return IntegrationHealthResponse(kind=kind, status=row.status, message="OK")
