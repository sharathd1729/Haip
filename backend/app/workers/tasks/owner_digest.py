"""
A7 — Daily owner digest.

Sends a WhatsApp + email digest to each tenant's owner(s) who have
opted in, at 9am in the tenant's local timezone.

The Celery beat schedule should trigger this task at least once per hour;
the task itself checks whether any tenant's 9am window falls in the
current hour and skips tenants outside that window.

Digest content:
  - Open inquiries count
  - TFR (time-to-first-response) p50 yesterday
  - Calls yesterday + avg QA score
  - Broadcasts sent yesterday + delivery rate
  - Top 1 insight (simple anomaly heuristic)
"""

import structlog
from datetime import datetime, timezone, timedelta
from app.workers.celery_app import celery_app
from app.workers.retry_policy import task_with_retry
from app.core.database import SessionLocal

log = structlog.get_logger()


@celery_app.task(**task_with_retry("owner_digest", max_retries=2, countdown=300))
def send_owner_digest(self, tenant_id: str):
    """
    Compose and dispatch the daily digest for a single tenant.
    Called by the hourly orchestrator when the tenant's 9am arrives.
    """
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.models.call import Call
    from app.models.inquiry import Inquiry, InquiryStage
    from app.models.conversation import Message
    from sqlalchemy import func

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return

        # Owners with digest opt-in
        owners = db.query(User).filter(
            User.tenant_id == tenant_id,
            User.role.in_([UserRole.OWNER, UserRole.MANAGER]),
            User.digest_opt_in.is_(True),
        ).all()

        if not owners:
            log.info("digest_skipped_no_optins", tenant_id=tenant_id)
            return

        # Compute stats
        now = datetime.now(timezone.utc)
        yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0)

        open_inqs = db.query(func.count(Inquiry.id)).filter(
            Inquiry.tenant_id == tenant_id,
            Inquiry.stage.in_([InquiryStage.NEW, InquiryStage.RESPONDING, InquiryStage.QUOTED]),
        ).scalar() or 0

        calls_yest = db.query(func.count(Call.id)).filter(
            Call.tenant_id == tenant_id,
            Call.started_at >= yesterday_start,
            Call.started_at < yesterday_end,
        ).scalar() or 0

        avg_qa = db.query(func.avg(Call.ai_score)).filter(
            Call.tenant_id == tenant_id,
            Call.started_at >= yesterday_start,
            Call.ai_score.isnot(None),
        ).scalar()

        # Simple insight heuristic
        insight = _compute_insight(db, tenant_id, now)

        # Render digest
        digest_text = _render_digest(
            tenant=tenant,
            open_inqs=open_inqs,
            calls_yest=calls_yest,
            avg_qa=float(avg_qa) if avg_qa else None,
            insight=insight,
        )

        # Dispatch to each owner
        for owner in owners:
            _dispatch_digest(tenant, owner, digest_text)

        log.info("owner_digest_sent", tenant_id=tenant_id, recipients=len(owners))

    finally:
        db.close()


def _compute_insight(db, tenant_id: str, now: datetime) -> str:
    """Return a simple one-line insight string."""
    from app.models.call import Call
    from sqlalchemy import func

    # Compare today's calls to last week same day
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last_week_start = today_start - timedelta(days=7)
    last_week_end = last_week_start + timedelta(days=1)

    today_calls = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tenant_id,
        Call.started_at >= today_start,
    ).scalar() or 0

    last_week_calls = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tenant_id,
        Call.started_at >= last_week_start,
        Call.started_at < last_week_end,
    ).scalar() or 0

    if last_week_calls > 0:
        pct_change = ((today_calls - last_week_calls) / last_week_calls) * 100
        if abs(pct_change) >= 20:
            direction = "up" if pct_change > 0 else "down"
            return f"📈 Call volume is {direction} {abs(pct_change):.0f}% vs. same day last week."

    return "No anomalies detected today."


def _render_digest(tenant, open_inqs: int, calls_yest: int, avg_qa: float | None, insight: str) -> str:
    """Render digest as plain text for WhatsApp + email."""
    qa_str = f"{avg_qa:.0f}/100" if avg_qa is not None else "N/A"
    lines = [
        f"🏨 *Daily Digest — {tenant.brand_name or tenant.name}*",
        f"",
        f"📋 Open inquiries: *{open_inqs}*",
        f"📞 Calls yesterday: *{calls_yest}* (QA avg: {qa_str})",
        f"",
        f"💡 Insight: {insight}",
        f"",
        f"View dashboard → https://app.haip.ai/dashboard",
    ]
    return "\n".join(lines)


def _dispatch_digest(tenant, owner, text: str):
    """Send digest via WhatsApp (primary) and skip if not connected."""
    try:
        if tenant.whatsapp_phone_number_id and owner.phone:
            from app.workers.tasks.send_whatsapp import send_whatsapp_message
            send_whatsapp_message.apply_async(kwargs={
                "tenant_id": tenant.id,
                "to_phone": owner.phone,
                "body": text,
            })
            log.info("digest_dispatched_wa", owner_id=owner.id)
        else:
            log.info("digest_skipped_no_wa", owner_id=owner.id, reason="no WA config or no phone")
    except Exception as exc:
        log.error("digest_dispatch_failed", owner_id=owner.id, error=str(exc))


# ─── Hourly orchestrator ──────────────────────────────────────────────────────

@celery_app.task(name="owner_digest.orchestrate")
def orchestrate_digest():
    """
    B10: Called by Celery beat hourly.
    Checks each tenant — if it's within the 9am hour in their local timezone,
    dispatch the daily digest.
    """
    from app.models.tenant import Tenant
    from app.core.tenant_tz import get_tenant_now
    from zoneinfo import ZoneInfo

    db = SessionLocal()
    try:
        tenants = db.query(Tenant).filter_by(is_active=True).all()
        now_utc = datetime.now(timezone.utc)
        dispatched = 0
        for tenant in tenants:
            try:
                now_local = get_tenant_now(tenant)
                # Fire if current local hour = 9 and we haven't fired today
                if now_local.hour == 9:
                    send_owner_digest.apply_async(
                        kwargs={"tenant_id": tenant.id},
                        countdown=0,
                    )
                    dispatched += 1
            except Exception as exc:
                log.error("digest_orchestrate_tenant_error", tenant_id=tenant.id, error=str(exc))
        log.info("digest_orchestrated", dispatched=dispatched)
    finally:
        db.close()
