"""
Ask HAIP — Phase 6: Alert Monitoring Celery Task

Runs every hour. For each active alert:
  1. Fetches current metric value from analytics data
  2. Evaluates threshold condition
  3. If triggered: creates Insight + sends email notification
  4. Prevents duplicate alerts (cooldown: 24h)

Supported metrics:
  revenue_mtd       → /analytics/executive → revenue_mtd
  occupancy_pct     → /analytics/executive → occupancy_pct
  high_risk_count   → /analytics/forecasting/churn → high_risk_count
  budget_objection_pct → /analytics/objections → budget_objection_pct
  sla_compliance_pct  → /analytics/executive → sla_compliance_pct
  active_inquiries    → /analytics/executive → active_inquiries
"""

import logging
from datetime import datetime, timezone, timedelta
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant

log = logging.getLogger(__name__)

METRIC_ENDPOINTS = {
    "revenue_mtd":           ("/analytics/executive",        "revenue_mtd"),
    "occupancy_pct":         ("/analytics/executive",        "occupancy_pct"),
    "sla_compliance_pct":    ("/analytics/executive",        "sla_compliance_pct"),
    "active_inquiries":      ("/analytics/executive",        "active_inquiries"),
    "high_risk_count":       ("/analytics/forecasting/churn","high_risk_count"),
    "budget_objection_pct":  ("/analytics/objections",       "budget_objection_pct"),
}

COOLDOWN_HOURS = 24   # don't re-fire the same alert within 24h


@shared_task(name="app.workers.tasks.check_alerts.check_all_tenants")
def check_all_tenants():
    """Fan out: check alerts for every active tenant."""
    db: Session = SessionLocal()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        for t in tenants:
            check_tenant_alerts.delay(str(t.id))
        return {"tenants": len(tenants)}
    finally:
        db.close()


@shared_task(name="app.workers.tasks.check_alerts.check_tenant_alerts",
             bind=True, max_retries=2)
def check_tenant_alerts(self, tenant_id: str):
    """Check all active alerts for a single tenant."""
    import asyncio
    db: Session = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        asyncio.run(_async_check(tenant_id, db))
    except Exception as exc:
        log.error("check_alerts failed tenant=%s error=%s", tenant_id, exc)
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()


async def _async_check(tenant_id: str, db: Session):
    from app.models.ask_haip_alert import AskHaipAlert
    from app.models.insight import Insight, InsightCategory, InsightSeverity
    from app.models.user import User
    from app.models.base import gen_uuid

    now = datetime.now(timezone.utc)
    alerts = db.query(AskHaipAlert).filter(
        AskHaipAlert.tenant_id == tenant_id,
        AskHaipAlert.is_active == True,
    ).all()

    if not alerts:
        return

    # Fetch analytics data once for all alerts
    metrics = await _fetch_metrics(tenant_id)

    for alert in alerts:
        # Cooldown check
        if alert.last_triggered_at:
            cooldown_until = alert.last_triggered_at + timedelta(hours=COOLDOWN_HOURS)
            if now < cooldown_until:
                continue

        current_value = metrics.get(alert.metric)
        if current_value is None:
            continue

        # Evaluate condition
        threshold = float(alert.threshold)
        triggered = False
        if alert.operator == "lt":   triggered = current_value < threshold
        elif alert.operator == "gt": triggered = current_value > threshold
        elif alert.operator == "lte": triggered = current_value <= threshold
        elif alert.operator == "gte": triggered = current_value >= threshold

        # Update last_checked_at
        alert.last_checked_at = now
        db.add(alert)

        if triggered:
            # Create insight
            insight = Insight(
                id=gen_uuid(),
                tenant_id=tenant_id,
                category_code=f"ALT_{alert.id[:6]}",
                target_id=str(alert.id),
                category=InsightCategory.REVENUE.value,
                severity=InsightSeverity.HIGH.value,
                title=f"Alert: {alert.name}",
                body=(f"Metric '{alert.metric}' is {current_value:.1f} "
                      f"({alert.operator} {threshold:.1f} threshold)"),
                cta_label="Investigate in Ask HAIP",
                cta_href="/dashboard/analytics/ask",
                expires_at=now + timedelta(hours=24),
            )
            db.add(insight)

            # Update alert state
            alert.last_triggered_at = now
            alert.trigger_count     = (alert.trigger_count or 0) + 1
            db.add(alert)

            # Email notification
            if alert.notify_email:
                owner = db.query(User).filter(
                    User.tenant_id == tenant_id,
                    User.role == "owner",
                ).first()
                if owner:
                    await _send_alert_email(
                        to_email=owner.email,
                        name=owner.full_name or owner.email,
                        alert_name=alert.name,
                        metric=alert.metric,
                        current_value=current_value,
                        threshold=threshold,
                        operator=alert.operator,
                    )

    db.commit()


async def _fetch_metrics(tenant_id: str) -> dict[str, float]:
    """
    Fetch current metric values directly from the DB (avoids service-token complexity).
    Returns a dict of metric_name → float value.
    """
    from app.core.database import SessionLocal, set_tenant_context
    from sqlalchemy import text

    db: Session = SessionLocal()
    metrics: dict[str, float] = {}
    try:
        set_tenant_context(db, tenant_id)
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # revenue_mtd — sum of booking values confirmed this calendar month
        row = db.execute(text("""
            SELECT COALESCE(SUM(total_amount), 0) AS v
            FROM bookings
            WHERE tenant_id = :tid
              AND status IN ('confirmed','checked_out')
              AND created_at >= :ms
        """), {"tid": tenant_id, "ms": month_start}).fetchone()
        if row:
            metrics["revenue_mtd"] = float(row.v)

        # active_inquiries — open inquiries
        row = db.execute(text("""
            SELECT COUNT(*) AS v FROM inquiries
            WHERE tenant_id = :tid AND status NOT IN ('lost','won','closed')
        """), {"tid": tenant_id}).fetchone()
        if row:
            metrics["active_inquiries"] = float(row.v)

        # occupancy_pct — (confirmed stays / total rooms) * 100 for current month
        row = db.execute(text("""
            SELECT
              CASE WHEN total > 0 THEN ROUND(100.0 * occupied / total, 1) ELSE 0 END AS v
            FROM (
              SELECT
                (SELECT COUNT(*) FROM stays
                 WHERE tenant_id = :tid AND check_in >= :ms AND status = 'checked_in') AS occupied,
                (SELECT COUNT(*) FROM villas WHERE tenant_id = :tid AND is_active = TRUE) AS total
            ) sub
        """), {"tid": tenant_id, "ms": month_start}).fetchone()
        if row:
            metrics["occupancy_pct"] = float(row.v)

        # sla_compliance_pct — calls responded within SLA / total calls * 100
        row = db.execute(text("""
            SELECT
              CASE WHEN total > 0
                   THEN ROUND(100.0 * within_sla / total, 1)
                   ELSE 100 END AS v
            FROM (
              SELECT
                COUNT(*) FILTER (WHERE response_time_seconds <= 300) AS within_sla,
                COUNT(*) AS total
              FROM calls
              WHERE tenant_id = :tid AND created_at >= :ms
            ) sub
        """), {"tid": tenant_id, "ms": month_start}).fetchone()
        if row:
            metrics["sla_compliance_pct"] = float(row.v)

        # high_risk_count — guests flagged high churn risk
        row = db.execute(text("""
            SELECT COUNT(*) AS v FROM guests
            WHERE tenant_id = :tid AND churn_risk = 'high'
        """), {"tid": tenant_id}).fetchone()
        if row:
            metrics["high_risk_count"] = float(row.v)

        # budget_objection_pct — budget objections / total objections * 100
        row = db.execute(text("""
            SELECT
              CASE WHEN total > 0
                   THEN ROUND(100.0 * budget / total, 1)
                   ELSE 0 END AS v
            FROM (
              SELECT
                COUNT(*) FILTER (WHERE objection_type ILIKE '%budget%' OR objection_type ILIKE '%price%') AS budget,
                COUNT(*) AS total
              FROM call_objections
              WHERE tenant_id = :tid AND created_at >= :ms
            ) sub
        """), {"tid": tenant_id, "ms": month_start}).fetchone()
        if row:
            metrics["budget_objection_pct"] = float(row.v)

    except Exception as exc:
        log.warning("_fetch_metrics failed for tenant=%s: %s", tenant_id, exc)
    finally:
        db.close()

    return metrics


async def _send_alert_email(*, to_email: str, name: str, alert_name: str,
                             metric: str, current_value: float,
                             threshold: float, operator: str):
    from app.services.email_service import _send
    op_labels = {"lt": "fell below", "gt": "exceeded", "lte": "is at or below", "gte": "reached"}
    op_label  = op_labels.get(operator, "crossed")
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">
      <h2 style="color:#0f766e;margin:0 0 8px">⚡ HAIP Alert Triggered</h2>
      <p style="color:#475569">Hi {name},</p>
      <p style="color:#475569">Your alert <strong>"{alert_name}"</strong> has been triggered.</p>
      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px;margin:16px 0">
        <p style="margin:0;font-size:14px;color:#991b1b">
          <strong>{metric.replace('_',' ').title()}</strong> {op_label} {threshold:.1f}
          <br>Current value: <strong>{current_value:.1f}</strong>
        </p>
      </div>
      <a href="/dashboard/analytics/ask" style="display:inline-block;background:#0f766e;color:white;
         padding:10px 20px;border-radius:8px;text-decoration:none;font-size:13px">
        Investigate in Ask HAIP →
      </a>
    </div>"""
    await _send(to=to_email, subject=f"HAIP Alert: {alert_name}", html=html)
