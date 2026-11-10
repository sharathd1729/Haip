"""The workspace's Meta Business connection (one System User token for ads, lead forms and Instagram).

  GET    /meta-business          what is connected and what the token can do (never the token)
  PUT    /meta-business/token    check a token with Meta, then save it encrypted
  POST   /meta-business/recheck  ask Meta again what the saved token can see
  PUT    /meta-business/page     choose the Facebook page
  DELETE /meta-business          remove the token
  POST   /meta-business/instagram  run Instagram messages on this token (the other way is Instagram Login)
  PUT    /meta-business/lead-forms         switch lead-form leads on or off
  POST   /meta-business/lead-forms/import  bring in the leads of the last N days (background)

Owners and managers only. Nothing here changes anything in Meta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.marketing.meta_ads import MetaAdsError
from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.core.database import get_db, set_tenant_context
from app.models.user import User, UserRole
from app.services import meta_business_service as svc
from app.services import meta_lead_forms_service as lead_forms

router = APIRouter(prefix="/meta-business", tags=["integrations"])

_Manager = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))


def _meta_error(exc: MetaAdsError) -> HTTPException:
    if exc.rate_limited:
        return HTTPException(status_code=429, detail="Meta is limiting requests right now. Try again in a few minutes.")
    if exc.bad_token:
        return HTTPException(status_code=400, detail=f"Meta rejected this token: {exc}")
    return HTTPException(status_code=502, detail=f"Meta did not answer: {exc}")


def _done(db: Session, user: User, action: str, payload: dict) -> dict:
    append_audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        target_type="integration",
        target_id=svc.KIND,
        payload=payload,
    )
    db.commit()
    set_tenant_context(db, user.tenant_id)
    return svc.status(db, user.tenant_id)


class TokenIn(BaseModel):
    access_token: str = Field(min_length=20, max_length=1000)


class PageIn(BaseModel):
    page_id: str = Field(min_length=3, max_length=40, pattern=r"^\d+$")


@router.get("")
def get_status(current_user: User = _Manager, db: Session = Depends(get_db)):
    return svc.status(db, current_user.tenant_id)


@router.put("/token")
def save_token(body: TokenIn, current_user: User = _Manager, db: Session = Depends(get_db)):
    try:
        row = svc.connect(db, current_user.tenant_id, body.access_token)
    except MetaAdsError as exc:
        raise _meta_error(exc) from exc
    caps = (row.config or {}).get("capabilities") or {}
    return _done(
        db,
        current_user,
        "meta_business.connected",
        {"token_name": (row.config or {}).get("token_name"), "can": sorted(k for k, v in caps.items() if v.get("ok"))},
    )


@router.post("/recheck")
def recheck(current_user: User = _Manager, db: Session = Depends(get_db)):
    try:
        svc.recheck(db, current_user.tenant_id)
    except svc.NotConnected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MetaAdsError as exc:
        raise _meta_error(exc) from exc
    db.commit()
    set_tenant_context(db, current_user.tenant_id)
    return svc.status(db, current_user.tenant_id)


@router.put("/page")
def choose_page(body: PageIn, current_user: User = _Manager, db: Session = Depends(get_db)):
    try:
        svc.select_page(db, current_user.tenant_id, body.page_id)
    except svc.NotConnected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _done(db, current_user, "meta_business.page_selected", {"page_id": body.page_id})


class LeadFormsIn(BaseModel):
    enabled: bool


class ImportIn(BaseModel):
    days: int = Field(lead_forms.MAX_IMPORT_DAYS, ge=1, le=lead_forms.MAX_IMPORT_DAYS)


@router.put("/lead-forms")
def set_lead_forms(body: LeadFormsIn, current_user: User = _Manager, db: Session = Depends(get_db)):
    try:
        lead_forms.set_enabled(db, current_user.tenant_id, body.enabled)
    except lead_forms.NotEnabled as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _done(
        db, current_user, "meta_business.lead_forms_on" if body.enabled else "meta_business.lead_forms_off", {}
    )


@router.post("/lead-forms/import", status_code=202)
def import_lead_forms(body: ImportIn, current_user: User = _Manager, db: Session = Depends(get_db)):
    """Queue an import of older form leads. Each lead is imported once, so running it twice adds nothing."""
    if not svc.status(db, current_user.tenant_id)["lead_forms"]["enabled"]:
        raise HTTPException(status_code=400, detail="Switch lead forms on first.")
    from app.workers.tasks.sync_meta_lead_forms import sync_tenant

    try:
        sync_tenant.apply_async(kwargs={"tenant_id": current_user.tenant_id, "since_days": body.days}, queue="whatsapp")
    except Exception as exc:  # noqa: BLE001  the broker is down
        raise HTTPException(status_code=503, detail="Could not start the import. Try again in a minute.") from exc
    return _done(db, current_user, "meta_business.lead_forms_import_started", {"days": body.days})


class InstagramIn(BaseModel):
    app_secret: str = Field(min_length=8, max_length=200)


@router.post("/instagram")
def use_for_instagram(body: InstagramIn, current_user: User = _Manager, db: Session = Depends(get_db)):
    """Instagram DMs and comments through the linked Facebook page's token. Instagram Login stays available."""
    try:
        ig = svc.use_for_instagram(db, current_user.tenant_id, body.app_secret)
    except svc.SwitchRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (svc.NotConnected, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MetaAdsError as exc:
        raise _meta_error(exc) from exc
    cfg = ig.config or {}
    return _done(
        db,
        current_user,
        "instagram.connected",
        {
            "mode": "meta_business",
            "instagram_business_account_id": cfg.get("instagram_business_account_id"),
            "webhook_subscribed": bool(cfg.get("webhook_subscribed")),
        },
    )


@router.delete("")
def disconnect(current_user: User = _Manager, db: Session = Depends(get_db)):
    if not svc.disconnect(db, current_user.tenant_id):
        raise HTTPException(status_code=404, detail="No Meta Business connection to remove.")
    return _done(db, current_user, "meta_business.disconnected", {})
