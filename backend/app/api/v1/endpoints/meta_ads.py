"""Meta ads data (Marketing > Ads). Owners, managers and the marketing role can read it; only owners and
managers choose which ad account is synced.

  GET  /marketing/ads/status    is an ad account chosen, when did it last sync
  GET  /marketing/ads/accounts  ad accounts the workspace's Meta token can read
  PUT  /marketing/ads/account   choose the ad account to sync
  POST /marketing/ads/sync      pull the last 30 days now
  POST /marketing/ads/backfill  load up to 36 months of history in the background (progress is in /status)
  GET  /marketing/ads/summary   spend, conversations, leads, bookings, revenue and ROAS per campaign

Reads only: nothing here changes anything in Meta.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.marketing.meta_ads import MetaAdsError
from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.core.database import get_db, set_tenant_context
from app.models.user import User, UserRole
from app.services import meta_ads_service

log = structlog.get_logger()
router = APIRouter(prefix="/marketing/ads", tags=["marketing"])

_Manager = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))
_Reader = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING))


def _meta_error(exc: MetaAdsError) -> HTTPException:
    """Say what went wrong in words an owner can act on. Never echo more of Meta's reply than its message."""
    if exc.rate_limited:
        return HTTPException(status_code=429, detail="Meta is limiting requests right now. Try again in a few minutes.")
    if exc.bad_token:
        return HTTPException(status_code=400, detail=f"Meta rejected the access token ({exc}). Save a new token under Settings, Integrations.")
    return HTTPException(status_code=502, detail=f"Meta did not answer: {exc}")


class AccountChoice(BaseModel):
    ad_account_id: str = Field(min_length=3, max_length=40, pattern=r"^(act_)?\d+$")


@router.get("/status")
def ads_status(current_user: User = _Reader, db: Session = Depends(get_db)):
    return meta_ads_service.status(db, current_user.tenant_id)


@router.get("/accounts")
def ads_accounts(current_user: User = _Manager, db: Session = Depends(get_db)):
    try:
        return {"accounts": meta_ads_service.list_accounts(db, current_user.tenant_id)}
    except meta_ads_service.NotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MetaAdsError as exc:
        raise _meta_error(exc)


@router.put("/account")
def choose_account(body: AccountChoice, current_user: User = _Manager, db: Session = Depends(get_db)):
    tenant_id = current_user.tenant_id
    try:
        accounts = meta_ads_service.list_accounts(db, tenant_id)
    except meta_ads_service.NotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MetaAdsError as exc:
        raise _meta_error(exc)
    wanted = body.ad_account_id if body.ad_account_id.startswith("act_") else f"act_{body.ad_account_id}"
    match = next((a for a in accounts if a["id"] == wanted), None)
    if match is None:
        # Never store an account the token cannot read: the nightly sync would fail every night.
        raise HTTPException(status_code=422, detail="This workspace's Meta token cannot read that ad account.")
    meta_ads_service.select_account(db, tenant_id, match["id"], match.get("name", ""), match.get("currency", "INR"))
    append_audit(db, tenant_id=tenant_id, actor_user_id=current_user.id, action="meta_ads.account_selected",
                 target_type="integration", target_id="meta_ads", payload={"ad_account_id": match["id"]})
    db.commit()
    set_tenant_context(db, tenant_id)
    return meta_ads_service.status(db, tenant_id)


@router.post("/sync")
def sync_now(current_user: User = _Reader, db: Session = Depends(get_db)):
    try:
        result = meta_ads_service.sync(db, current_user.tenant_id, days=meta_ads_service.BACKFILL_DAYS)
    except meta_ads_service.NotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MetaAdsError as exc:
        raise _meta_error(exc)
    return {**result, **meta_ads_service.status(db, current_user.tenant_id)}


class BackfillRequest(BaseModel):
    months: int = Field(12, ge=1, le=meta_ads_service.MAX_BACKFILL_MONTHS)


@router.post("/backfill", status_code=202)
def start_backfill(body: BackfillRequest, current_user: User = _Manager, db: Session = Depends(get_db)):
    """Queue a history load. It runs in the background a month at a time; GET /status shows `backfill` progress."""
    tenant_id = current_user.tenant_id
    try:
        meta_ads_service._require(db, tenant_id)
    except meta_ads_service.NotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    row = meta_ads_service.get_row(db, tenant_id)
    state = (row.config or {}).get("backfill") or {}
    if state.get("state") in ("running", "queued") and state.get("started_at"):
        try:
            started = datetime.fromisoformat(state["started_at"])
        except ValueError:
            started = None
        if started and datetime.now(timezone.utc) - started < timedelta(minutes=30):
            raise HTTPException(status_code=409, detail="A history load is already running.")
    meta_ads_service._mark(db, row, backfill={"state": "queued", "started_at": meta_ads_service._now_iso(),
                                              "months": body.months, "total": len(meta_ads_service.backfill_plan(body.months)),
                                              "done": 0, "rows": 0, "failed": [], "stopped_because": None})
    try:
        meta_ads_service.queue_backfill(tenant_id, body.months)
    except Exception as exc:
        log.error("meta_ads_backfill_not_queued", tenant_id=tenant_id, error=str(exc)[:200])
        meta_ads_service._mark(db, row, backfill={**(row.config or {}).get("backfill", {}), "state": "stopped", "stopped_because": "not_queued"})
        raise HTTPException(status_code=503, detail="Could not start the history load. Try again in a minute.") from exc
    append_audit(db, tenant_id=tenant_id, actor_user_id=current_user.id, action="meta_ads.backfill_started",
                 target_type="integration", target_id="meta_ads", payload={"months": body.months})
    db.commit()
    set_tenant_context(db, tenant_id)
    return meta_ads_service.status(db, tenant_id)


@router.get("/summary")
def ads_summary(days: int = Query(30, ge=1, le=1100), current_user: User = _Reader, db: Session = Depends(get_db)):
    return meta_ads_service.summary(db, current_user.tenant_id, days)
