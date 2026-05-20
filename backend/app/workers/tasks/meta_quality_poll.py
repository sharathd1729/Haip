"""
S7 — Meta quality-rating poll.

Hourly Celery beat task that fetches WABA quality rating + messaging tier
from the Meta Graph API for every active tenant that has WhatsApp configured.
Stores snapshots in meta_quality_snapshots table.
"""
import uuid
import httpx
from datetime import datetime, timezone
import structlog
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal, Base
from sqlalchemy import Column, String, JSON, Numeric
from app.models.base import TimestampMixin, gen_uuid

log = structlog.get_logger()

META_GRAPH_URL = "https://graph.facebook.com/v19.0"


# ── Inline model ──────────────────────────────────────────────────────────────
class MetaQualitySnapshot(Base, TimestampMixin):
    __tablename__ = "meta_quality_snapshots"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    waba_id = Column(String(100), nullable=False)
    quality_rating = Column(String(20), nullable=True)   # GREEN | YELLOW | RED | UNKNOWN
    messaging_limit_tier = Column(String(50), nullable=True)
    raw = Column(JSON, nullable=True)


@celery_app.task(name="meta_quality.poll_all_tenants")
def poll_all_tenants():
    db = SessionLocal()
    try:
        from app.models.tenant import Tenant
        tenants = db.query(Tenant).filter(
            Tenant.is_active == True,  # noqa
            Tenant.whatsapp_config.isnot(None),
        ).all()
        for tenant in tenants:
            cfg = tenant.whatsapp_config or {}
            waba_id = cfg.get("waba_id")
            token = cfg.get("access_token")
            if not waba_id or not token:
                continue
            try:
                _poll_tenant(db, tenant.id, waba_id, token)
            except Exception as exc:
                log.error("meta_quality_poll_failed", tenant_id=tenant.id, error=str(exc))
        db.commit()
    finally:
        db.close()


def _poll_tenant(db, tenant_id: str, waba_id: str, token: str) -> None:
    url = f"{META_GRAPH_URL}/{waba_id}"
    params = {
        "fields": "quality_rating,messaging_limit_tier",
        "access_token": token,
    }
    try:
        resp = httpx.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("meta_quality_api_error", tenant_id=tenant_id, waba_id=waba_id, error=str(exc))
        return

    snap = MetaQualitySnapshot(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        waba_id=waba_id,
        quality_rating=data.get("quality_rating", "UNKNOWN"),
        messaging_limit_tier=data.get("messaging_limit_tier"),
        raw=data,
    )
    db.add(snap)

    log.info(
        "meta_quality_polled",
        tenant_id=tenant_id,
        quality_rating=snap.quality_rating,
        tier=snap.messaging_limit_tier,
    )
