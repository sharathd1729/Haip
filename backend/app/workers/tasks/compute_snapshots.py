"""
compute_snapshots — nightly per-tenant metric snapshot computation.
Reads metrics_registry sql_template rows and writes to metric_snapshots.
Runs nightly at 01:00 IST for all tenants.
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone, timedelta
from celery import shared_task
from sqlalchemy import text

from app.core.database import SessionLocal
from app.models.metric_registry import MetricRegistry
from app.models.dashboard_v2 import MetricSnapshot
from app.models.tenant import Tenant
from app.models.base import gen_uuid

log = structlog.get_logger()


@shared_task(name="app.workers.tasks.compute_snapshots.run_all_tenants", bind=True, max_retries=2)
def run_all_tenants(self):
    """Fan-out: spawn one compute_for_tenant per active tenant."""
    with SessionLocal() as db:
        tenant_ids = [r.id for r in db.query(Tenant.id).filter(Tenant.is_active == True).all()]
    for tid in tenant_ids:
        compute_for_tenant.delay(tid)
    log.info("compute_snapshots_dispatched", tenant_count=len(tenant_ids))
    return {"dispatched": len(tenant_ids)}


@shared_task(name="app.workers.tasks.compute_snapshots.compute_for_tenant", bind=True, max_retries=3)
def compute_for_tenant(self, tenant_id: str):
    """
    For each active metric in metrics_registry with a sql_template,
    execute the template for yesterday and upsert into metric_snapshots.
    """
    with SessionLocal() as db:
        metrics = db.query(MetricRegistry).filter(
            MetricRegistry.sql_template.isnot(None)
        ).all()

        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)

        computed = 0
        for metric in metrics:
            try:
                result = db.execute(
                    text(metric.sql_template),
                    {
                        "tenant_id": tenant_id,
                        "start_date": yesterday,
                        "end_date": today,
                        "property_ids": None,
                    },
                ).fetchone()
                value = str(result[0]) if result and result[0] is not None else "0"

                existing = db.query(MetricSnapshot).filter(
                    MetricSnapshot.workspace_id == tenant_id,
                    MetricSnapshot.metric_key == metric.metric_key,
                    MetricSnapshot.period_date == yesterday,
                    MetricSnapshot.granularity == "day",
                    MetricSnapshot.property_id == None,
                ).first()

                if existing:
                    existing.value = value
                    existing.computed_at = datetime.now(timezone.utc)
                else:
                    db.add(MetricSnapshot(
                        id=gen_uuid(),
                        workspace_id=tenant_id,
                        metric_key=metric.metric_key,
                        property_id=None,
                        period_date=yesterday,
                        granularity="day",
                        value=value,
                        dimensions={},
                    ))
                computed += 1
            except Exception as exc:
                log.warning("metric_compute_failed",
                            tenant_id=tenant_id,
                            metric_key=metric.metric_key,
                            error=str(exc))

        db.commit()
        log.info("compute_snapshots_done",
                 tenant_id=tenant_id,
                 computed=computed,
                 total=len(metrics))
    return {"tenant_id": tenant_id, "computed": computed}
