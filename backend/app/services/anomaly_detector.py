"""
A8 — Anomaly highlights on analytics charts.

Computes z-scores against a rolling 14-day mean to flag outlier days.
Exposed via GET /analytics/anomalies?metric=calls&range_days=30.
"""

import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, DateTime
import structlog

log = structlog.get_logger()


def detect_anomalies(
    values: List[Dict[str, Any]],
    value_key: str = "count",
    threshold: float = 2.0,
    window: int = 14,
) -> List[Dict[str, Any]]:
    """
    For each data point, compute the z-score against the rolling `window`-day
    mean and stddev. Points where |z| > threshold are flagged as anomalies.

    Args:
        values: List of dicts with at least {date: str, <value_key>: float}
        value_key: Which field to analyse (default "count")
        threshold: Z-score threshold (default 2.0 = 2σ)
        window: Rolling window size (default 14 days)

    Returns:
        Same list with added keys:
          z_score: float
          is_anomaly: bool
          direction: "high" | "low" | None
          rolling_mean: float
          rolling_std: float
    """
    n = len(values)
    result = []

    for i, point in enumerate(values):
        val = float(point.get(value_key, 0) or 0)
        # Rolling window: last `window` points (exclusive of current)
        window_start = max(0, i - window)
        window_vals = [float(values[j].get(value_key, 0) or 0) for j in range(window_start, i)]

        if len(window_vals) < 3:
            # Not enough history
            result.append({**point, "z_score": 0.0, "is_anomaly": False, "direction": None,
                           "rolling_mean": val, "rolling_std": 0.0})
            continue

        mean = sum(window_vals) / len(window_vals)
        variance = sum((v - mean) ** 2 for v in window_vals) / len(window_vals)
        std = math.sqrt(variance)

        if std == 0:
            z = 0.0
        else:
            z = (val - mean) / std

        is_anomaly = abs(z) > threshold
        direction = "high" if z > threshold else ("low" if z < -threshold else None)

        result.append({
            **point,
            "z_score": round(z, 2),
            "is_anomaly": is_anomaly,
            "direction": direction,
            "rolling_mean": round(mean, 2),
            "rolling_std": round(std, 2),
        })

    return result


def get_call_anomalies(db: Session, tenant_id: str, range_days: int = 30) -> List[Dict]:
    """Fetch daily call counts for a tenant and return anomaly-annotated series."""
    from app.models.call import Call

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=range_days + 14)  # +14 for warmup window

    # Call.started_at is stored as String (ISO datetime text), not a native
    # timestamp column -- Postgres has no >= operator between varchar and
    # timestamptz, so both the filter and the date() grouping need an
    # explicit cast rather than relying on implicit coercion.
    started_at_ts = cast(Call.started_at, DateTime(timezone=True))
    rows = db.query(
        func.date(started_at_ts).label("d"),
        func.count(Call.id).label("count"),
        func.coalesce(func.avg(Call.ai_score), 0).label("avg_score"),
    ).filter(
        Call.tenant_id == tenant_id,
        started_at_ts >= start,
    ).group_by("d").order_by("d").all()

    series = [{"date": str(r.d), "count": r.count, "avg_score": float(r.avg_score)} for r in rows]
    annotated = detect_anomalies(series, value_key="count")

    # Return only the requested range (exclude warmup)
    cutoff = (now - timedelta(days=range_days)).date().isoformat()
    return [p for p in annotated if p["date"] >= cutoff]
