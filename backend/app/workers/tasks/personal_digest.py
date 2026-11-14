"""tasks `personal.daily_digest_all_tenants` (beat, 22:00 IST) and `personal.daily_digest` (one workspace): Yaad's
"Your day at a glance" email (services/personal_digest.py + personal_digest_email.py).

Personal workspaces only. Recipients: active OWNER users with an email who have not switched it off
(`notification_prefs.daily_summary_email`, default on). Once per workspace per day: the day is marked sent in Redis only
after a successful send, so a failed send retries (twice, 10 minutes apart) and a re-run after success sends nothing.
"""

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import structlog

from app.core import cache
from app.core.config import settings
from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import personal_calls as pc
from app.services import personal_digest as svc
from app.services import personal_digest_email as email
from app.workers.celery_app import celery_app

log = structlog.get_logger()

PREF_KEY = "daily_summary_email"
IST = ZoneInfo("Asia/Kolkata")
SENT_TTL = 3 * 86400


def _sent_key(tenant_id: str, day: str) -> str:
    return f"haip:personal_digest:sent:{tenant_id}:{day}"


def recipients(db, tenant_id: str) -> list[User]:
    users = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.role == UserRole.OWNER,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        .all()
    )
    return [u for u in users if u.email and (u.notification_prefs or {}).get(PREF_KEY, True) is not False]


@celery_app.task(name="personal.daily_digest", bind=True, max_retries=2)
def daily_digest(self, tenant_id: str, day: str | None = None, to_email: str | None = None) -> dict:
    """Email one personal workspace its day. `to_email` sends one test copy there (not marked sent)."""
    from app.services.email_service import _send

    day = day or datetime.now(IST).date().isoformat()
    if not to_email and cache.get_cached(_sent_key(tenant_id, day)):
        return {"tenant_id": tenant_id, "day": day, "status": "already_sent"}
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not pc.is_personal_tenant(tenant):
            return {"tenant_id": tenant_id, "status": "not_personal"}
        users = recipients(db, tenant_id)
        targets = [to_email] if to_email else [u.email for u in users]
        if not targets:
            log.info("personal_digest_no_recipients", tenant_id=tenant_id)
            return {"tenant_id": tenant_id, "status": "no_recipients"}
        first_name = users[0].name.split()[0] if users and (users[0].name or "").strip() else "you"
        digest = svc.build(db, tenant_id, date.fromisoformat(day), first_name)
    finally:
        db.close()
    if digest is None:
        log.info("personal_digest_quiet_day", tenant_id=tenant_id, day=day)
        return {"tenant_id": tenant_id, "day": day, "status": "no_calls"}

    app_url = settings.FRONTEND_URL or ""
    subject, html, text = email.subject(digest), email.html(digest, app_url), email.text(digest, app_url)
    sent = sum(bool(asyncio.run(_send(addr, subject, html, text))) for addr in targets)
    if not sent:
        log.error("personal_digest_send_failed", tenant_id=tenant_id, day=day, recipients=len(targets))
        raise self.retry(countdown=600)
    if not to_email:
        cache.set_cached(_sent_key(tenant_id, day), True, ttl=SENT_TTL)
    log.info("personal_digest_sent", tenant_id=tenant_id, day=day, sent=sent, calls=digest["stats"]["calls"])
    return {"tenant_id": tenant_id, "day": day, "status": "sent", "sent": sent}


@celery_app.task(name="personal.daily_digest_all_tenants")
def daily_digest_all_tenants() -> dict:
    """Queue today's email for every active personal workspace."""
    if not settings.RESEND_API_KEY:
        log.warning("personal_digest_skipped_no_email_key")
        return {"tenants_queued": 0, "reason": "no_email_key"}
    day = datetime.now(IST).date().isoformat()
    db = SessionLocal()
    try:
        ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all() if pc.is_personal_tenant(t)]
    finally:
        db.close()
    for tid in ids:
        daily_digest.delay(tid, day)
    log.info("personal_digest_queued", tenants=len(ids), day=day)
    return {"tenants_queued": len(ids), "day": day}
