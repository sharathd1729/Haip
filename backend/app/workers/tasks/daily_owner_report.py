"""The owner's daily brief email (option C, owner pick 21 Oct 2026): morning brief at 08:00 IST (yesterday) and evening check at
19:00 IST (today so far), built by owner_brief_service and rendered by owner_brief_email.

Recipients: active OWNER / MANAGER users with an email who have not switched it off (``notification_prefs.morning_brief_email``,
default on; Settings > Notifications). Booking money is shown only to readers with ``bookings.read``. Nothing is sent on a day
with no activity and nothing to do. Task names and beat entries are unchanged from the old report.
"""

import asyncio

import structlog
from celery import shared_task

from app.core.config import settings
from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import owner_brief_email, owner_brief_service

log = structlog.get_logger()

PREF_KEY = "morning_brief_email"


def _app_url() -> str:
    return (settings.FRONTEND_URL or "").rstrip("/")


def recipients(db, tenant_id: str) -> list[User]:
    users = (db.query(User).filter(User.tenant_id == tenant_id, User.role.in_([UserRole.OWNER, UserRole.MANAGER]),
                                   User.is_active.is_(True), User.is_deleted.is_(False)).all())
    return [u for u in users if u.email and (u.notification_prefs or {}).get(PREF_KEY, True) is not False]


@shared_task(name="reports.send_daily_owner_report", bind=True, max_retries=2)
def send_daily_owner_report(self, tenant_id: str, day: str | None = None, to_email: str | None = None, kind: str = "morning"):
    """Build and email one workspace's brief. ``to_email`` sends one copy there instead (manual test), even on a quiet day.
    ``day`` is accepted for old callers and ignored: the brief always covers yesterday (morning) or today so far (evening)."""
    from app.services.authz_service import has_capability
    from app.services.email_service import _send

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            log.warning("owner_brief_tenant_missing", tenant_id=tenant_id)
            return {"tenant_id": tenant_id, "status": "no_tenant"}
        name = tenant.brand_name or tenant.name

        targets = [(to_email, True)] if to_email else [(u.email, has_capability(db, u, "bookings.read"))
                                                        for u in recipients(db, tenant_id)]
        if not targets:
            log.info("owner_brief_no_recipients", tenant_id=tenant_id)
            return {"tenant_id": tenant_id, "status": "no_recipients"}

        briefs: dict[bool, dict] = {}
        sent = failed = 0
        for addr, money in targets:
            if money not in briefs:
                briefs[money] = owner_brief_service.build(db, tenant, kind=kind, app_url=_app_url(), money=money)
            brief = briefs[money]
            if not brief["worth_sending"] and not to_email:
                log.info("owner_brief_skipped_quiet_day", tenant_id=tenant_id, kind=kind, day=brief["day"])
                return {"tenant_id": tenant_id, "status": "quiet_day", "day": brief["day"]}
            ok = asyncio.run(_send(addr, owner_brief_email.subject(brief, name), owner_brief_email.html(brief, name),
                                   owner_brief_email.text(brief, name)))
            sent, failed = sent + bool(ok), failed + (not ok)
        day_sent = next(iter(briefs.values()))["day"]
        log.info("owner_brief_sent", tenant_id=tenant_id, kind=kind, day=day_sent, sent=sent, failed=failed)
        return {"tenant_id": tenant_id, "kind": kind, "day": day_sent, "sent": sent, "failed": failed}
    finally:
        db.close()


@shared_task(name="reports.daily_owner_report_all_tenants")
def daily_owner_report_all_tenants(kind: str = "morning"):
    """Fan out to every active workspace. Beat fires this at 08:00 (morning) and 19:00 (evening) IST."""
    if not settings.RESEND_API_KEY:
        # Without a key nothing can be sent; skip loudly instead of looking healthy.
        log.warning("owner_brief_skipped_no_email_key")
        return {"tenants_queued": 0, "reason": "no_email_key"}
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()
    for tid in tenant_ids:
        send_daily_owner_report.delay(tid, kind=kind)
    log.info("owner_brief_queued", tenants=len(tenant_ids), kind=kind)
    return {"tenants_queued": len(tenant_ids), "kind": kind}
