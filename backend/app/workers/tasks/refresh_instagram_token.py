"""
Keep Instagram long-lived access tokens alive.

Real incident (Ratha, Sep 2026): the Instagram token issued at connect time
expired on 10-Sep. Every outbound DM from then on failed with "Error
validating access token: Session has expired", 36 in a row across five
days, while the concierge bot happily kept drafting replies within ~15s of
each inbound message. Leads saw silence; the product looked dead.

The integration only ever exchanged for a long-lived token
(ig_exchange_token, 60 days) at connect time and then never touched it
again -- nothing refreshed it, and its expiry was never even stored, so
there was nothing to monitor either. check_meta_credentials.py alerts once
a token is ALREADY dead; by then Meta will not take it back:
"tokens not refreshed within 60 days will expire permanently and become
non-refreshable", at which point the only cure is a human redoing OAuth.

So this runs daily and refreshes well ahead of expiry. Per Meta's docs a
long-lived token can be refreshed once it is at least 24h old and still
valid, and each refresh buys another 60 days -- so a daily refresh keeps
the window permanently topped up, and a tenant would have to be offline
for a full 60 days to lose it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import structlog
from celery import shared_task

from app.core.database import SessionLocal
from app.models.integration import Integration
from app.models.tenant import Tenant

log = structlog.get_logger()

REFRESH_URL = "https://graph.instagram.com/refresh_access_token"

# Meta requires a token to be >=24h old before it can be refreshed. A fresh
# OAuth connect therefore gets skipped on its first day rather than logged
# as a failure.
_MIN_TOKEN_AGE = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@shared_task(name="instagram_token.refresh_tenant")
def refresh_tenant_token(tenant_id: str) -> dict:
    from app.core.encryption import decrypt_credentials, encrypt_credentials

    db = SessionLocal()
    try:
        integ = (
            db.query(Integration)
            .filter_by(tenant_id=tenant_id, kind="instagram", status="active")
            .first()
        )
        if not integ or not integ.credentials_kms_blob:
            return {"tenant_id": tenant_id, "status": "not_configured"}

        creds = decrypt_credentials(integ.credentials_kms_blob)
        access_token = creds.get("access_token", "")
        if not access_token:
            return {"tenant_id": tenant_id, "status": "no_token"}

        config = dict(integ.config or {})

        # Too young to refresh -- Meta rejects these, so don't spend the call.
        issued_at = _parse_iso(config.get("token_refreshed_at")) or (
            integ.installed_at.replace(tzinfo=timezone.utc)
            if getattr(integ, "installed_at", None) and integ.installed_at.tzinfo is None
            else getattr(integ, "installed_at", None)
        )
        if issued_at and _now() - issued_at < _MIN_TOKEN_AGE:
            return {"tenant_id": tenant_id, "status": "too_young"}

        try:
            resp = httpx.get(
                REFRESH_URL,
                params={"grant_type": "ig_refresh_token", "access_token": access_token},
                timeout=15,
            )
        except Exception as exc:
            # Network trouble is not a dead token -- try again tomorrow.
            log.warning("instagram_token_refresh_network_error", tenant_id=tenant_id, error=str(exc))
            return {"tenant_id": tenant_id, "status": "network_error"}

        if resp.status_code != 200:
            # Already expired, revoked, or wrong audience. Nothing this task
            # can do -- a human has to redo OAuth. check_meta_credentials
            # owns alerting so this doesn't double-notify.
            log.error(
                "instagram_token_refresh_failed",
                tenant_id=tenant_id,
                status_code=resp.status_code,
                detail=resp.text[:300],
            )
            return {"tenant_id": tenant_id, "status": "refresh_failed", "http": resp.status_code}

        data = resp.json()
        new_token = data.get("access_token")
        if not new_token:
            log.error("instagram_token_refresh_no_token", tenant_id=tenant_id, body=str(data)[:300])
            return {"tenant_id": tenant_id, "status": "no_token_in_response"}

        expires_in = int(data.get("expires_in") or 0)
        creds["access_token"] = new_token
        integ.credentials_kms_blob = encrypt_credentials(creds)

        config["token_refreshed_at"] = _now().isoformat()
        if expires_in:
            config["token_expires_at"] = (_now() + timedelta(seconds=expires_in)).isoformat()
        integ.config = config
        db.commit()

        log.info(
            "instagram_token_refreshed",
            tenant_id=tenant_id,
            expires_in_days=round(expires_in / 86400, 1) if expires_in else None,
        )
        return {"tenant_id": tenant_id, "status": "refreshed", "expires_in": expires_in}
    finally:
        db.close()


@shared_task(name="instagram_token.refresh_all_tenants")
def refresh_all_tenants() -> dict:
    """Fan out -- one refresh subtask per active tenant."""
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()

    for tid in tenant_ids:
        refresh_tenant_token.apply_async(kwargs={"tenant_id": tid}, queue="whatsapp")
    log.info("instagram_token_refresh_queued", tenants=len(tenant_ids))
    return {"tenants_queued": len(tenant_ids)}
