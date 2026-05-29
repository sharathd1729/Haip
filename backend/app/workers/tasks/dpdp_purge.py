"""
DPDP purge task — daily at 02:00 IST.
Hard-deletes guests tombstoned past their grace window and purges revoked refresh tokens.
"""
import boto3
from datetime import datetime, timezone, timedelta
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.guest import Guest
from app.models.user import RefreshToken
from app.core.config import settings
from app.core.audit import append_audit
import structlog

log = structlog.get_logger()

GRACE_DAYS = 90          # 90-day right-to-erasure window
TOKEN_PURGE_DAYS = 90    # purge revoked tokens after 90 days


@celery_app.task(name="tasks.dpdp_purge")
def dpdp_purge():
    """
    Daily DPDP compliance purge:
      1. Hard-delete soft-deleted guests older than GRACE_DAYS.
      2. Hard-delete revoked refresh tokens older than TOKEN_PURGE_DAYS.
    """
    from app.core.database import set_tenant_context
    from app.models.tenant import Tenant
    from sqlalchemy import text

    db = SessionLocal()
    try:
        stats: dict = {"guests_purged": 0, "tokens_purged": 0}
        guest_cutoff = (datetime.now(timezone.utc) - timedelta(days=GRACE_DAYS)).isoformat()

        # ── 1. Hard-delete tombstoned guests (process per-tenant for RLS) ─────
        # First discover which tenants have guests to purge using a raw query
        # (bypasses ORM-level RLS, safe because this is a superuser maintenance task
        # and we immediately validate with per-tenant context below)
        tenant_rows = db.execute(
            text(
                "SELECT DISTINCT tenant_id FROM guests "
                "WHERE is_deleted = TRUE AND deleted_at <= :cutoff"
            ),
            {"cutoff": guest_cutoff},
        ).fetchall()

        for (tenant_id_val,) in tenant_rows:
            set_tenant_context(db, str(tenant_id_val))
            to_purge = (
                db.query(Guest)
                .filter(
                    Guest.is_deleted == True,
                    Guest.deleted_at <= guest_cutoff,
                )
                .all()
            )
            for guest in to_purge:
                _purge_s3(guest.tenant_id, guest.id)
                append_audit(
                    db,
                    tenant_id=guest.tenant_id,
                    action="dpdp.purge_complete",
                    target_type="guest",
                    target_id=guest.id,
                    payload={"phone_prefix": guest.phone[:8] if guest.phone else None},
                )
                db.delete(guest)
                stats["guests_purged"] += 1

        # ── 2. Hard-delete revoked refresh tokens (not tenant-scoped) ────────
        token_cutoff = datetime.now(timezone.utc) - timedelta(days=TOKEN_PURGE_DAYS)
        deleted_tokens = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.is_revoked == True,
                RefreshToken.created_at <= token_cutoff.isoformat(),
            )
            .delete(synchronize_session=False)
        )
        stats["tokens_purged"] = deleted_tokens

        db.commit()
        log.info("dpdp_purge_complete", **stats)
    finally:
        db.close()


def _purge_s3(tenant_id: str, guest_id: str):
    """Delete all S3 objects under tenant/<tid>/guest/<gid>/."""
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        prefix = f"{tenant_id}/guest/{guest_id}/"
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.S3_BUCKET_NAME, Prefix=prefix):
            objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objects:
                s3.delete_objects(Bucket=settings.S3_BUCKET_NAME, Delete={"Objects": objects})
    except Exception as e:
        log.warning("s3_purge_failed", tenant_id=tenant_id, guest_id=guest_id, error=str(e))
