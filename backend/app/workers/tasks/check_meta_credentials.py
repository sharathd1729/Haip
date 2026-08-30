"""
Proactive WhatsApp/Instagram access-token health check.

Real incident that motivated this: Ratha's Instagram access token expired
silently -- Meta long-lived tokens last ~60 days, and this one was never
refreshed or monitored after connecting. Every outbound send since then
failed with a 403 Forbidden, completely unnoticed until an agent found a
stuck conversation and it got escalated. Neither WhatsApp nor Instagram
integrations had any expiry/health monitoring anywhere in the codebase.

Runs daily. For each tenant with an active whatsapp_meta/whatsapp or
instagram Integration, makes one cheap read-only Graph API call using the
exact same credentials real sends use (_get_wa_access_token for WhatsApp,
the same encrypted-blob decrypt Instagram sends already use) -- if Meta
rejects it with 401/403, the token is dead or revoked, and every
owner/manager on the tenant gets an email alert. Deduped to once per 24h
per (tenant, channel) via the existing cache helpers so a persistently
dead token doesn't spam an inbox on every run.
"""
import httpx
import structlog
from celery import shared_task

from app.core.cache import get_cached, set_cached
from app.core.database import SessionLocal, set_tenant_context
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole

log = structlog.get_logger()

_ALERT_DEDUPE_TTL = 24 * 60 * 60  # one alert per (tenant, channel) per day


def _recipients(db, tenant_id: str) -> list[str]:
    return [
        u.email for u in db.query(User).filter(
            User.tenant_id == tenant_id,
            User.role.in_([UserRole.OWNER, UserRole.MANAGER]),
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        ).all()
        if u.email
    ]


def _check_whatsapp(db, tenant_id: str):
    """Returns (is_valid, detail) or None if WhatsApp isn't configured for
    this tenant at all."""
    from app.workers.tasks.whatsapp import _get_wa_access_token

    integ = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp_meta", status="active").first()
    if not integ:
        integ = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp", status="active").first()
    if not integ:
        return None

    phone_number_id = (integ.config or {}).get("phone_number_id")
    access_token = _get_wa_access_token(db, tenant_id)
    if not phone_number_id or not access_token:
        return False, "Missing phone_number_id or access_token"

    try:
        resp = httpx.get(
            f"https://graph.facebook.com/v20.0/{phone_number_id}",
            params={"fields": "id", "access_token": access_token},
            timeout=10,
        )
        if resp.status_code in (401, 403):
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        resp.raise_for_status()
        return True, "ok"
    except httpx.HTTPStatusError as exc:
        return False, f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    except Exception as exc:
        # Network/timeout errors are not proof the token is dead -- don't
        # alert on transient connectivity issues, just skip this run.
        log.warning("meta_credential_check_network_error", tenant_id=tenant_id, channel="whatsapp", error=str(exc))
        return None


def _check_instagram(db, tenant_id: str):
    """Returns (is_valid, detail) or None if Instagram isn't configured."""
    from app.core.encryption import decrypt_credentials

    integ = db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram", status="active").first()
    if not integ or not integ.credentials_kms_blob:
        return None

    creds = decrypt_credentials(integ.credentials_kms_blob)
    access_token = creds.get("access_token", "")
    ig_account_id = (integ.config or {}).get("instagram_business_account_id")
    if not access_token or not ig_account_id:
        return False, "Missing access_token or instagram_business_account_id"

    try:
        resp = httpx.get(
            f"https://graph.instagram.com/v20.0/{ig_account_id}",
            params={"fields": "id", "access_token": access_token},
            timeout=10,
        )
        if resp.status_code in (401, 403):
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        resp.raise_for_status()
        return True, "ok"
    except httpx.HTTPStatusError as exc:
        return False, f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    except Exception as exc:
        log.warning("meta_credential_check_network_error", tenant_id=tenant_id, channel="instagram", error=str(exc))
        return None


@shared_task(name="meta_credentials.check_tenant")
def check_tenant_credentials(tenant_id: str):
    from app.services.email_service import send_integration_expired_alert_email
    import asyncio

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return {"tenant_id": tenant_id, "status": "no_tenant"}

        checks = {"whatsapp": _check_whatsapp(db, tenant_id), "instagram": _check_instagram(db, tenant_id)}
        alerts_sent = 0

        for channel, result in checks.items():
            if result is None:
                continue  # not configured, or a transient network error -- nothing to report
            is_valid, detail = result
            if is_valid:
                continue

            dedupe_key = f"haip:meta_cred_alert:{tenant_id}:{channel}"
            if get_cached(dedupe_key):
                log.info("meta_credential_alert_deduped", tenant_id=tenant_id, channel=channel)
                continue

            log.error("meta_credential_check_failed", tenant_id=tenant_id, channel=channel, detail=detail)
            targets = _recipients(db, tenant_id)
            for addr in targets:
                asyncio.run(send_integration_expired_alert_email(
                    to_email=addr, tenant_name=tenant.name, channel=channel, detail=detail,
                ))
                alerts_sent += 1
            set_cached(dedupe_key, True, ttl=_ALERT_DEDUPE_TTL)

        return {"tenant_id": tenant_id, "alerts_sent": alerts_sent}
    finally:
        db.close()


@shared_task(name="meta_credentials.check_all_tenants")
def check_all_tenants():
    """Fan out -- one check_tenant_credentials subtask per active tenant."""
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()

    for tid in tenant_ids:
        check_tenant_credentials.apply_async(kwargs={"tenant_id": tid}, queue="whatsapp")
    log.info("meta_credentials_check_queued", tenants=len(tenant_ids))
    return {"tenants_queued": len(tenant_ids)}
