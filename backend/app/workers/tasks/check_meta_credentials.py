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
from app.models.integration import INSTAGRAM_INBOUND_STATUSES, Integration
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


# ── Instagram: is Meta still letting us see messages? ─────────────────────────
#
# Real incident (Ratha, 24-Sep-2026): DMs stopped reaching the inbox for about
# 15 hours while the access token was perfectly valid. The account's own
# "Allow access to messages" switch in the Instagram app was off, so Meta
# answered every Direct Messaging call with 403 "The account owner has
# disabled access to Instagram Direct Messaging" and delivered no message
# events. The token check above can't see this -- it only reads the account
# node -- and its email talks about expired tokens, which sends the team down
# the wrong road.
#
# So this asks for one page of conversations, hourly, and alerts on that exact
# refusal. Anything else (a dead token, missing Advanced Access, an outage, a
# timeout) says nothing about the switch and is left to the check above.

_IG_GRAPH = "https://graph.instagram.com/v21.0"
_DM_ACCESS_ALERT_KEY = "haip:ig_dm_access_alert:{tenant_id}"
_DM_DISABLED_PHRASE = "disabled access to instagram direct messaging"


def _is_dm_access_disabled(resp) -> bool:
    """Meta's refusal for an account whose owner switched message access off:
    HTTP 403, IGApiException code 200, and that sentence. Matching all three
    keeps an ordinary permissions error (also code 200 in places) from
    raising a false alarm."""
    if resp.status_code != 403:
        return False
    try:
        err = (resp.json() or {}).get("error") or {}
    except Exception:
        return False
    return err.get("code") == 200 and _DM_DISABLED_PHRASE in str(err.get("message", "")).lower()


def _check_instagram_dm_access(db, tenant_id: str):
    """Returns (is_open, detail), or None when there is nothing conclusive to
    say -- no Instagram connection, or any answer other than "fine" / "the
    owner switched it off"."""
    from app.core.encryption import decrypt_credentials

    integ = (
        db.query(Integration)
        .filter(
            Integration.tenant_id == tenant_id,
            Integration.kind == "instagram",
            Integration.status.in_(INSTAGRAM_INBOUND_STATUSES),
        )
        .first()
    )
    if not integ or not integ.credentials_kms_blob:
        return None
    token = decrypt_credentials(integ.credentials_kms_blob).get("access_token", "")
    if not token:
        return None

    try:
        resp = httpx.get(
            f"{_IG_GRAPH}/me/conversations",
            params={"limit": 1, "access_token": token},
            timeout=10,
        )
    except Exception as exc:
        log.warning("instagram_dm_access_probe_network_error", tenant_id=tenant_id, error=str(exc))
        return None

    if resp.status_code == 200:
        return True, "ok"
    if _is_dm_access_disabled(resp):
        return False, "The account owner has disabled access to Instagram Direct Messaging."
    log.info(
        "instagram_dm_access_probe_inconclusive",
        tenant_id=tenant_id, status_code=resp.status_code, detail=resp.text[:200],
    )
    return None


@shared_task(name="meta_credentials.check_instagram_dm_access_tenant")
def check_instagram_dm_access_tenant(tenant_id: str):
    from app.services.email_service import send_instagram_dm_access_alert_email
    import asyncio

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return {"tenant_id": tenant_id, "status": "no_tenant"}

        result = _check_instagram_dm_access(db, tenant_id)
        if result is None:
            return {"tenant_id": tenant_id, "status": "skipped", "alerts_sent": 0}

        dedupe_key = _DM_ACCESS_ALERT_KEY.format(tenant_id=tenant_id)
        is_open, detail = result
        if is_open:
            # Clear the last alert so a relapse tomorrow alerts straight away
            # instead of waiting out that alert's 24h.
            if get_cached(dedupe_key):
                set_cached(dedupe_key, False, ttl=1)
            return {"tenant_id": tenant_id, "status": "open", "alerts_sent": 0}

        # Error level so it also shows up in the server logs, not only email.
        log.error("instagram_dm_access_disabled", tenant_id=tenant_id, detail=detail)
        if get_cached(dedupe_key):
            return {"tenant_id": tenant_id, "status": "disabled", "alerts_sent": 0}

        alerts_sent = 0
        for addr in _recipients(db, tenant_id):
            try:
                if asyncio.run(send_instagram_dm_access_alert_email(to_email=addr, tenant_name=tenant.name)):
                    alerts_sent += 1
            except Exception as exc:
                log.error("instagram_dm_access_alert_send_failed", tenant_id=tenant_id, error=str(exc))
        # Only remember the alert once someone actually got it, so a failed
        # send is retried on the next hourly run instead of waiting a day.
        if alerts_sent:
            set_cached(dedupe_key, True, ttl=_ALERT_DEDUPE_TTL)
        return {"tenant_id": tenant_id, "status": "disabled", "alerts_sent": alerts_sent}
    finally:
        db.close()


@shared_task(name="meta_credentials.check_instagram_dm_access")
def check_instagram_dm_access_all():
    """Fan out -- one Instagram message-access probe per active tenant."""
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()

    for tid in tenant_ids:
        check_instagram_dm_access_tenant.apply_async(kwargs={"tenant_id": tid}, queue="whatsapp")
    log.info("instagram_dm_access_check_queued", tenants=len(tenant_ids))
    return {"tenants_queued": len(tenant_ids)}
