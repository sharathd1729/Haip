"""Public API usage log: one row per call made with an API key (method, route template, status, duration).

record() runs after the response has been sent (a background task of the public API middleware), with its own
session; a failed write is logged and dropped, never raised. Rows are kept 30 days (webhooks.purge_old).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.api_usage_log import ApiUsageLog

log = structlog.get_logger()

RECENT_LIMIT = 100


def record(tenant_id: str, api_key_id: str, method: str, path: str, status_code: int, duration_ms: int) -> None:
    from app.core.database import SessionLocal, set_tenant_context
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        db.add(ApiUsageLog(tenant_id=tenant_id, api_key_id=api_key_id, method=method[:8], path=path[:200],
                           status_code=status_code, duration_ms=max(0, int(duration_ms))))
        db.commit()
    except Exception as exc:  # noqa: BLE001 -- the log must never affect the API call itself
        db.rollback()
        log.warning("api_usage_log_write_failed", error=str(exc)[:200])
    finally:
        db.close()


def usage(db: Session, tenant_id: str, api_key_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = (db.query(ApiUsageLog).filter(ApiUsageLog.tenant_id == tenant_id, ApiUsageLog.api_key_id == api_key_id)
            .order_by(ApiUsageLog.created_at.desc()).limit(RECENT_LIMIT).all())
    week = (db.query(func.count(ApiUsageLog.id))
            .filter(ApiUsageLog.tenant_id == tenant_id, ApiUsageLog.api_key_id == api_key_id,
                    ApiUsageLog.created_at >= now - timedelta(days=7)).scalar() or 0)
    return {
        "calls_7d": int(week),
        "recent": [{"method": r.method, "path": r.path, "status": r.status_code, "duration_ms": r.duration_ms,
                    "at": r.created_at.isoformat() if r.created_at else None} for r in rows],
    }
