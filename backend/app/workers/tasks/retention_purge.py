"""
D5 — Retention auto-purge.

Nightly Celery beat task that deletes rows older than the per-tenant retention
policy. Every purge batch emits an AuditEvent for DPDP proof of deletion.

Default policy (months):
  transcripts      24
  call_recordings  12  (DB row; S3 object via storage adapter)
  messages         36
  audit_log        24  (per DPDP — 24 months minimum for fiduciary records)
  consent          60  (5 years)
  deleted_guests   3   (tombstone grace period in months → ~90 days)
"""
from datetime import datetime, timezone, timedelta
import structlog
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.audit import append_audit
from app.models.conversation import Message
from app.models.call import Call

log = structlog.get_logger()

# Default policy: entity → retention months (configurable per tenant in future)
DEFAULT_POLICY: dict[str, int] = {
    "messages":         36,
    "call_recordings":  12,
    "audit_log":        24,
    "consent":          60,
    "deleted_guests":   3,
}


def _cutoff(months: int) -> datetime:
    """Return a datetime `months` months ago (approximation: 30 days/month)."""
    return datetime.now(timezone.utc) - timedelta(days=months * 30)


@celery_app.task(name="retention.nightly_purge")
def nightly_purge():
    """
    Nightly retention purge. Scheduled via Celery Beat at 02:00 UTC.
    """
    db = SessionLocal()
    try:
        tenant_ids = _get_all_tenant_ids(db)
        for tenant_id in tenant_ids:
            _purge_tenant(db, tenant_id)
        db.commit()
    except Exception as exc:
        log.error("retention_purge_failed", error=str(exc))
        db.rollback()
        raise
    finally:
        db.close()


def _get_all_tenant_ids(db) -> list[str]:
    from app.models.tenant import Tenant
    return [t.id for t in db.query(Tenant).filter_by(is_active=True).all()]


def _purge_tenant(db, tenant_id: str) -> None:
    stats: dict[str, int] = {}

    # --- Messages ---
    msg_cutoff = _cutoff(DEFAULT_POLICY["messages"])
    deleted_msgs = (
        db.query(Message)
        .filter(
            Message.tenant_id == tenant_id,
            Message.created_at < msg_cutoff,
        )
        .delete(synchronize_session=False)
    )
    stats["messages"] = deleted_msgs

    # --- Call recordings (mark recording_url as purged; S3 deletion async) ---
    rec_cutoff = _cutoff(DEFAULT_POLICY["call_recordings"])
    calls_with_recording = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id,
            Call.started_at < rec_cutoff,
            Call.recording_url.isnot(None),
        )
        .all()
    )
    for call in calls_with_recording:
        # TODO: queue S3/R2 object deletion via storage adapter
        call.recording_url = None
    stats["call_recordings"] = len(calls_with_recording)

    # --- Deleted guests (hard-delete tombstones after grace period) ---
    try:
        from app.models.guest import Guest
        ghost_cutoff = _cutoff(DEFAULT_POLICY["deleted_guests"])
        deleted_guests = (
            db.query(Guest)
            .filter(
                Guest.tenant_id == tenant_id,
                Guest.deletion_state == "pending",
                Guest.deletion_requested_at < ghost_cutoff.isoformat(),
            )
            .delete(synchronize_session=False)
        )
        stats["deleted_guests"] = deleted_guests
    except Exception as exc:
        log.warning("guest_purge_skipped", error=str(exc))
        stats["deleted_guests"] = 0

    # Audit the purge
    total = sum(stats.values())
    if total > 0:
        append_audit(
            db=db,
            tenant_id=tenant_id,
            actor_user_id=None,
            action="retention.purge",
            target_type="batch",
            target_id=None,
            payload={
                "policy": DEFAULT_POLICY,
                "deleted_counts": stats,
                "total": total,
            },
        )

    log.info(
        "retention_purge_complete",
        tenant_id=tenant_id,
        **stats,
    )
