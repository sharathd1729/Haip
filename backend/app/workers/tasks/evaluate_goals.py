"""
evaluate_goals — daily goal progress check.
Compares latest metric_snapshots against goals.target_value.
Fires alerts when progress < alert_at_pct and period not yet over.
Runs daily at 08:00 IST.
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone

from celery import shared_task

from app.core.database import SessionLocal
from app.models.dashboard_v2 import Goal, MetricSnapshot
from app.models.tenant import Tenant

log = structlog.get_logger()


@shared_task(name="app.workers.tasks.evaluate_goals.run_all_tenants", bind=True, max_retries=2)
def run_all_tenants(self):
    with SessionLocal() as db:
        tenant_ids = [r.id for r in db.query(Tenant.id).filter(Tenant.is_active == True).all()]
    for tid in tenant_ids:
        evaluate_for_tenant.delay(tid)
    return {"dispatched": len(tenant_ids)}


@shared_task(name="app.workers.tasks.evaluate_goals.evaluate_for_tenant", bind=True, max_retries=3)
def evaluate_for_tenant(self, tenant_id: str):
    """
    For each active goal (period_end >= now), fetch latest snapshot value
    and compare against target. Write alert if below threshold.
    """
    from sqlalchemy import func

    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        goals = db.query(Goal).filter(
            Goal.workspace_id == tenant_id,
            Goal.period_end >= now,
        ).all()

        if not goals:
            return {"tenant_id": tenant_id, "goals_checked": 0}

        metric_keys = list({g.metric_key for g in goals})
        subq = (
            db.query(
                MetricSnapshot.metric_key,
                func.max(MetricSnapshot.period_date).label("max_date"),
            )
            .filter(
                MetricSnapshot.workspace_id == tenant_id,
                MetricSnapshot.metric_key.in_(metric_keys),
            )
            .group_by(MetricSnapshot.metric_key)
            .subquery()
        )
        latest_rows = db.query(MetricSnapshot).join(
            subq,
            (MetricSnapshot.metric_key == subq.c.metric_key) &
            (MetricSnapshot.period_date == subq.c.max_date),
        ).filter(MetricSnapshot.workspace_id == tenant_id).all()
        latest_map = {r.metric_key: float(r.value) for r in latest_rows}

        below_threshold = []
        for g in goals:
            target = float(g.target_value)
            current = latest_map.get(g.metric_key, 0.0)
            pct = (current / target * 100) if target > 0 else 0.0

            if pct < g.alert_at_pct:
                severity = "warning" if pct >= g.alert_at_pct * 0.75 else "critical"
                log.warning("goal_below_threshold",
                            tenant_id=tenant_id,
                            goal_id=g.id,
                            goal_name=g.name,
                            metric_key=g.metric_key,
                            current=current,
                            target=target,
                            progress_pct=round(pct, 1),
                            severity=severity)
                below_threshold.append({"goal_id": g.id, "progress_pct": round(pct, 1)})
            else:
                log.info("goal_on_track",
                         tenant_id=tenant_id,
                         goal_id=g.id,
                         progress_pct=round(pct, 1))

        log.info("evaluate_goals_done",
                 tenant_id=tenant_id,
                 goals_checked=len(goals),
                 below_threshold=len(below_threshold))
    return {
        "tenant_id": tenant_id,
        "goals_checked": len(goals),
        "below_threshold": below_threshold,
    }
