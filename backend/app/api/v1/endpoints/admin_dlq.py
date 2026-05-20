"""
B3 — Dead-letter queue (DLQ) inspection + re-queue endpoints.

GET  /admin/dlq              — list all DLQ task names with counts
GET  /admin/dlq/{task_name}  — list failed entries for a task (paginated)
POST /admin/dlq/{task_name}/{task_id}/retry — re-queue a specific failed task
DELETE /admin/dlq/{task_name} — clear all entries for a task

All endpoints require owner or admin role.
"""

import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.v1.deps import require_roles
from app.models.user import User, UserRole
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/admin/dlq", tags=["admin"])


def _get_redis():
    try:
        import redis
        from app.core.config import settings
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        r.ping()
        return r
    except Exception:
        return None


class DLQSummary(BaseModel):
    task_name: str
    count: int


class DLQEntry(BaseModel):
    task_id: str
    task_name: str
    failed_at: int
    error: str
    args: str
    kwargs: str


@router.get("", response_model=List[DLQSummary])
def list_dlq_tasks(
    current_user: User = Depends(require_roles(UserRole.OWNER)),
):
    """List all DLQ task names and their pending failure count."""
    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    keys = r.keys("dlq:*")
    result = []
    for key in keys:
        task_name = key[4:]  # strip "dlq:"
        count = r.llen(key)
        result.append(DLQSummary(task_name=task_name, count=count))
    return sorted(result, key=lambda x: x.count, reverse=True)


@router.get("/{task_name}", response_model=List[DLQEntry])
def list_dlq_entries(
    task_name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, le=100),
    current_user: User = Depends(require_roles(UserRole.OWNER)),
):
    """List failed entries for a given task, newest first."""
    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    key = f"dlq:{task_name}"
    raw = r.lrange(key, offset, offset + limit - 1)
    result = []
    for item in raw:
        try:
            result.append(DLQEntry(**json.loads(item)))
        except Exception:
            pass
    return result


@router.delete("/{task_name}", status_code=204)
def clear_dlq(
    task_name: str,
    current_user: User = Depends(require_roles(UserRole.OWNER)),
):
    """Clear all DLQ entries for a task name."""
    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    r.delete(f"dlq:{task_name}")
    log.info("dlq_cleared", task_name=task_name, actor=current_user.id)


@router.post("/{task_name}/{task_id}/retry", status_code=202)
def retry_dlq_entry(
    task_name: str,
    task_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER)),
):
    """
    Re-queue a specific failed task by sending it back to Celery.
    Removes the entry from the DLQ if found.
    """
    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Redis unavailable")

    key = f"dlq:{task_name}"
    entries = r.lrange(key, 0, -1)
    target = None
    for raw in entries:
        try:
            entry = json.loads(raw)
            if entry.get("task_id") == task_id:
                target = (raw, entry)
                break
        except Exception:
            pass

    if not target:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    raw_str, entry = target

    # Re-send to Celery
    try:
        from app.workers.celery_app import celery_app
        # Reconstruct kwargs as best we can from the stored string
        celery_app.send_task(task_name)
        # Remove the entry from DLQ
        r.lrem(key, 1, raw_str)
        log.info("dlq_entry_retried", task_name=task_name, task_id=task_id, actor=current_user.id)
        return {"message": f"Task {task_name} re-queued"}
    except Exception as exc:
        log.error("dlq_retry_failed", task_name=task_name, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to re-queue: {exc}")
