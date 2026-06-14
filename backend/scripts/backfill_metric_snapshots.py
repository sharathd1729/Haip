"""
Backfill last 90 days of metric snapshots for all active tenants.
Run off-peak: python scripts/backfill_metric_snapshots.py

Uses the same SQL templates in metrics_registry.
Skips metrics with no sql_template (manual/derived metrics).
Processes one tenant at a time to avoid table-scan overload.

Risk: MEDIUM — run off-peak on prod. Monitor DB CPU during execution.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from app.core.database import SessionLocal
from app.models.metric_registry import MetricRegistry
from app.models.dashboard_v2 import MetricSnapshot
from app.models.tenant import Tenant
from app.models.base import gen_uuid

BACKFILL_DAYS = 90
GRANULARITY = "day"


def backfill_tenant(db, tenant_id: str, metrics, period_dates):
    computed = skipped = errors = 0
    for metric in metrics:
        for period_date in period_dates:
            # Skip if already exists
            existing = db.query(MetricSnapshot).filter(
                MetricSnapshot.workspace_id == tenant_id,
                MetricSnapshot.metric_key == metric.metric_key,
                MetricSnapshot.period_date == period_date,
                MetricSnapshot.granularity == GRANULARITY,
                MetricSnapshot.property_id == None,
            ).first()
            if existing:
                skipped += 1
                continue

            end_date = period_date + timedelta(days=1)
            try:
                result = db.execute(
                    text(metric.sql_template),
                    {
                        "tenant_id": tenant_id,
                        "start_date": period_date,
                        "end_date": end_date,
                        "property_ids": None,
                    },
                ).fetchone()
                value = str(result[0]) if result and result[0] is not None else "0"

                db.add(MetricSnapshot(
                    id=gen_uuid(),
                    workspace_id=tenant_id,
                    metric_key=metric.metric_key,
                    property_id=None,
                    period_date=period_date,
                    granularity=GRANULARITY,
                    value=value,
                    dimensions={},
                ))
                computed += 1
            except Exception as exc:
                errors += 1
                # Log but continue — don't abort entire backfill on one bad metric
                print(f"    SKIP metric={metric.metric_key} date={period_date.date()} err={exc}")

    db.commit()
    return computed, skipped, errors


def main():
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    period_dates = [today - timedelta(days=i) for i in range(1, BACKFILL_DAYS + 1)]

    with SessionLocal() as db:
        tenants = db.query(Tenant.id, Tenant.name).filter(Tenant.is_active == True).all()
        metrics = db.query(MetricRegistry).filter(MetricRegistry.sql_template.isnot(None)).all()

        print(f"Backfilling {len(period_dates)} days × {len(metrics)} metrics × {len(tenants)} tenants")
        print(f"Total potential rows: {len(period_dates) * len(metrics) * len(tenants):,}\n")

        for tenant in tenants:
            print(f"→ {tenant.name} ({tenant.id[:8]}…)", end=" ", flush=True)
            c, s, e = backfill_tenant(db, tenant.id, metrics, period_dates)
            print(f"computed={c} skipped={s} errors={e}")

    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
