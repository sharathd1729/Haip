"""Website > Grow and the website SEO agency (services/website_seo_agency.py), staff API under /api/v1/websites.

Read = website.read; agency settings, a manual run and applying the technical checker's fixes = website.approve
(owner/manager). Money: website booking value needs bookings.read, ad spend / revenue needs revenue.read. The run is a
Celery task (it may call the LLM; never inline in a request).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services import website_seo_agency as agency
from app.services import website_service as svc
from app.services.authz_service import has_capability, require_capability

router = APIRouter(prefix="/websites", tags=["website"])
_module = Depends(require_module("website"))
_read = Depends(require_capability("website.read"))
_approve = Depends(require_capability("website.approve"))


class AgencyIn(BaseModel):
    roles: dict[str, str] | None = None
    paused: bool | None = None


def _fail(exc: svc.WebsiteError):
    raise HTTPException(
        status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems}
    )


@router.get("/grow")
def grow(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.api.v1.endpoints.website import user_can_see_money

    tenant = db.get(Tenant, user.tenant_id)
    return agency.grow(
        db,
        tenant,
        show_money=user_can_see_money(db, user),
        show_ads_money=bool(has_capability(db, user, "revenue.read")),
    )


@router.put("/seo-agency")
def put_agency(
    body: AgencyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve
):
    tenant = db.get(Tenant, user.tenant_id)
    try:
        out = agency.update_settings(db, tenant, user.id, roles=body.roles, paused=body.paused)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return {"settings": out, "roster": agency.roster(tenant)}


@router.post("/seo-agency/run", status_code=202)
def run_now(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    tenant = db.get(Tenant, user.tenant_id)
    if agency.get_settings(tenant)["paused"]:
        _fail(svc.WebsiteError(409, "agency_paused", "The SEO agency is paused. Switch it back on to run it."))
    from app.workers.tasks.website_seo_agency import run_week

    run_week.delay(user.tenant_id, "manual", user.id)
    return {"queued": True}


@router.post("/seo-agency/fixes/apply")
def apply_fixes(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    from app.services import website_seo_fixes as fixes

    tenant = db.get(Tenant, user.tenant_id)
    if agency.get_settings(tenant)["paused"]:
        _fail(svc.WebsiteError(409, "agency_paused", "The SEO agency is paused. Switch it back on first."))
    try:
        site = svc.require_site(db, user.tenant_id)
        done = fixes.apply(db, tenant, site, actor_id=user.id)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return done
