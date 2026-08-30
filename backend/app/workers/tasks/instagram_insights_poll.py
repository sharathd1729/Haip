"""
Organic Instagram account insights -- daily snapshot.

Same shape as meta_quality_poll.py (inline model, avoid a new Alembic
migration for a small polling feature -- established precedent in this
codebase, see messaging.py's own inline-models docstring). Confirmed live
against Ratha's connected account: reach + follower_count both return
real, non-zero data; profile_views is requested too but Meta may silently
omit any metric not available for a given account/period rather than
erroring the whole call.
"""
import uuid
import httpx
import structlog
from celery import shared_task
from sqlalchemy import Column, String, JSON, Integer

from app.core.database import SessionLocal, Base
from app.core.encryption import decrypt_credentials
from app.models.base import TimestampMixin, gen_uuid
from app.models.integration import Integration

log = structlog.get_logger()

_METRICS = ["reach", "profile_views", "follower_count"]


class InstagramInsightsSnapshot(Base, TimestampMixin):
    __tablename__ = "instagram_insights_snapshots"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ig_account_id = Column(String(100), nullable=False)
    reach = Column(Integer, nullable=True)
    profile_views = Column(Integer, nullable=True)
    follower_count = Column(Integer, nullable=True)
    raw = Column(JSON, nullable=True)


@shared_task(name="instagram_insights.poll_all_tenants")
def poll_all_tenants():
    db = SessionLocal()
    try:
        integrations = db.query(Integration).filter_by(kind="instagram", status="active").all()
        for integ in integrations:
            try:
                _poll_tenant(db, integ)
            except Exception as exc:
                log.error("instagram_insights_poll_failed", tenant_id=integ.tenant_id, error=str(exc))
        db.commit()
        log.info("instagram_insights_polled", tenants=len(integrations))
        return {"tenants_polled": len(integrations)}
    finally:
        db.close()


def _poll_tenant(db, integ: Integration) -> None:
    if not integ.credentials_kms_blob:
        return
    creds = decrypt_credentials(integ.credentials_kms_blob)
    access_token = creds.get("access_token", "")
    ig_account_id = (integ.config or {}).get("instagram_business_account_id", "")
    if not access_token or not ig_account_id:
        return

    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    adapter = InstagramGraphAdapter(access_token=access_token, ig_account_id=ig_account_id)

    try:
        results = adapter.get_account_insights(_METRICS, period="day")
    except httpx.HTTPStatusError as exc:
        log.warning(
            "instagram_insights_api_error", tenant_id=integ.tenant_id,
            status=exc.response.status_code, body=exc.response.text[:300],
        )
        return

    values_by_metric = {}
    for metric in results:
        vals = metric.get("values", [])
        if vals:
            values_by_metric[metric["name"]] = vals[-1].get("value")

    db.add(InstagramInsightsSnapshot(
        id=str(uuid.uuid4()),
        tenant_id=integ.tenant_id,
        ig_account_id=ig_account_id,
        reach=values_by_metric.get("reach"),
        profile_views=values_by_metric.get("profile_views"),
        follower_count=values_by_metric.get("follower_count"),
        raw=results,
    ))
