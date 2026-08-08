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


def _tenant_has_any_data(db, tenant_id: str) -> bool:
    """A tenant with zero rows anywhere metrics could read from genuinely
    should compute 0 metrics -- that's correct, not a bug. Distinguishes
    that from the silent-zero bug this guard exists to catch (Dashboard
    Metrics Plan F1: every metrics_registry row had sql_template=NULL, so
    compute_for_tenant always computed 0 and logged success regardless of
    how much real data existed)."""
    from app.models.call import Call
    from app.models.inquiry import Inquiry
    from app.models.conversation import Message

    for model in (Call, Inquiry, Message):
        if db.query(model.id).filter(model.tenant_id == tenant_id).first():
            return True
    return False


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

        if computed == 0 and _tenant_has_any_data(db, tenant_id):
            # Same failure class as the Alembic "logs success, commits
            # nothing" bug documented in CLAUDE.md -- a tenant with real
            # data getting zero computed metrics means the registry (e.g.
            # every row's sql_template is NULL -- the exact F1 bug) or the
            # templates themselves are broken, not that there's nothing to
            # report. Deliberately fires even when `metrics` itself is
            # empty -- that IS the bug this guard exists to catch. Fail
            # loudly instead of silently logging success.
            raise RuntimeError(
                f"compute_snapshots computed 0 metrics for tenant {tenant_id} "
                f"({len(metrics)} metrics_registry rows had a non-null sql_template) "
                f"despite existing tenant data"
            )

        log.info("compute_snapshots_done",
                 tenant_id=tenant_id,
                 computed=computed,
                 total=len(metrics))
    return {"tenant_id": tenant_id, "computed": computed}
