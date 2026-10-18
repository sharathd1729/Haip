"""Before / after impact view (owner + manager) and the public case study.

  GET    /dashboard/impact                      the view (go_live / days default to the saved settings)
  GET    /dashboard/impact/export.pdf           the same, as a PDF for sales decks (aggregates only)
  PUT    /dashboard/impact/settings             go-live date + window (owner)
  GET    /dashboard/impact/baselines            the owner-entered "before" figures
  PUT    /dashboard/impact/baselines/{metric}   create or change one (owner, audited)
  DELETE /dashboard/impact/baselines/{metric}   remove one (owner, audited)
  GET    /dashboard/impact/case-study           publish status + the published snapshot
  POST   /dashboard/impact/case-study/publish   freeze the numbers into the public snapshot (owner, audited)
  POST   /dashboard/impact/case-study/withdraw  back to "coming soon" (owner, audited)
  GET    /case-studies, /case-studies/{slug}    PUBLIC: published snapshots only, never anything else

Money needs revenue.read: without it the money tiles and the revenue block are ``{"restricted": true}``.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.impact import BaselineIn, CaseStudyPublishIn, ImpactSettingsIn
from app.services import impact_case_study as case_study
from app.services import impact_pdf
from app.services import impact_service as svc
from app.services.authz_service import get_capabilities, require_capability

router = APIRouter(prefix="/dashboard/impact", tags=["impact"])
public_router = APIRouter(prefix="/case-studies", tags=["case-studies"])

_VIEWERS = require_roles(UserRole.OWNER, UserRole.MANAGER)
_OWNER = require_roles(UserRole.OWNER)


def _can_revenue(db: Session, user: User) -> bool:
    return "revenue.read" in get_capabilities(db, user)


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).first()


def _view(db: Session, user: User, go_live: Optional[date], days: Optional[int]) -> dict:
    try:
        return svc.build(db, _tenant(db, user), go_live=go_live, days=days, can_revenue=_can_revenue(db, user))
    except svc.ImpactError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("")
def impact_view(
    go_live: Optional[date] = Query(None, description="YYYY-MM-DD (IST); defaults to the saved go-live date"),
    days: Optional[int] = Query(None, ge=7, le=180, description="Window length in days; defaults to the saved one (30)"),
    current_user: User = Depends(_VIEWERS),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("analytics.read")),
):
    view = _view(db, current_user, go_live, days)
    profile = svc.get_profile(db, current_user.tenant_id)
    view["saved"] = {"go_live": profile.go_live_date.isoformat() if profile and profile.go_live_date else None,
                     "days": profile.window_days if profile else svc.DEFAULT_DAYS}
    view["can_edit"] = current_user.role == UserRole.OWNER
    view["can_revenue"] = _can_revenue(db, current_user)
    return view


@router.get("/export.pdf")
def impact_pdf_export(
    go_live: Optional[date] = Query(None),
    days: Optional[int] = Query(None, ge=7, le=180),
    current_user: User = Depends(_VIEWERS),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("analytics.read")),
):
    view = _view(db, current_user, go_live, days)
    if view.get("needs_go_live"):
        raise HTTPException(status_code=422, detail="Set the go-live date first")
    tenant = _tenant(db, current_user)
    pdf = impact_pdf.render(view, brand_name=tenant.name or "Workspace")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="impact-{view["windows"]["with"]["to"]}.pdf"'})


@router.put("/settings")
def save_settings(body: ImpactSettingsIn, current_user: User = Depends(_OWNER), db: Session = Depends(get_db)):
    try:
        p = svc.save_settings(db, current_user.tenant_id, current_user.id, body.go_live_date, body.window_days)
    except svc.ImpactError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"go_live": p.go_live_date.isoformat(), "days": p.window_days}


@router.get("/baselines")
def list_baselines(current_user: User = Depends(_VIEWERS), db: Session = Depends(get_db)):
    can_revenue = _can_revenue(db, current_user)
    rows = svc.baselines_for(db, current_user.tenant_id)
    out = []
    for key, spec in svc.BASELINE_METRICS.items():
        item = {"metric": key, "label": spec["label"], "unit": spec["unit"], "definition": spec["definition"]}
        if spec["money"] and not can_revenue:
            out.append({**item, "restricted": True})
            continue
        b = rows.get(key)
        out.append({**item, "restricted": False, "baseline": svc._baseline_out(b) if b else None})
    return {"metrics": out, "can_edit": current_user.role == UserRole.OWNER}


@router.put("/baselines/{metric}")
def put_baseline(metric: str, body: BaselineIn, current_user: User = Depends(_OWNER), db: Session = Depends(get_db)):
    if metric not in svc.BASELINE_METRICS:
        raise HTTPException(status_code=404, detail="Unknown metric")
    row = svc.save_baseline(db, current_user.tenant_id, current_user.id, metric, body.value, body.period_label, body.source_note)
    return svc._baseline_out(row)


@router.delete("/baselines/{metric}", status_code=204)
def remove_baseline(metric: str, current_user: User = Depends(_OWNER), db: Session = Depends(get_db)):
    if not svc.delete_baseline(db, current_user.tenant_id, current_user.id, metric):
        raise HTTPException(status_code=404, detail="No baseline for that metric")
    return Response(status_code=204)


@router.get("/case-study")
def case_study_status(current_user: User = Depends(_VIEWERS), db: Session = Depends(get_db)):
    return {**case_study.status(db, current_user.tenant_id), "can_edit": current_user.role == UserRole.OWNER}


@router.post("/case-study/publish")
def case_study_publish(body: CaseStudyPublishIn, current_user: User = Depends(_OWNER), db: Session = Depends(get_db)):
    try:
        return case_study.publish(db, _tenant(db, current_user), current_user, slug=body.slug, brand_name=body.brand_name,
                                  headline=body.headline, summary=body.summary, include_revenue=body.include_revenue,
                                  can_revenue=_can_revenue(db, current_user))
    except svc.ImpactError as exc:
        status = 409 if "already used" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc))


@router.post("/case-study/withdraw")
def case_study_withdraw(current_user: User = Depends(_OWNER), db: Session = Depends(get_db)):
    try:
        return case_study.withdraw(db, current_user.tenant_id, current_user.id)
    except svc.ImpactError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ── public ───────────────────────────────────────────────────────────────────────────────────────────────────

@public_router.get("")
def public_case_studies(db: Session = Depends(get_db)):
    return {"items": case_study.published(db)}


@public_router.get("/{slug}")
def public_case_study(slug: str, db: Session = Depends(get_db)):
    """A published snapshot, or ``coming_soon``. Same 200 answer for an unknown, a draft and a withdrawn slug, so the page
    never tells whether a workspace exists."""
    if not case_study.SLUG_RE.match(slug or ""):
        return {"status": "coming_soon", "slug": slug}
    found = case_study.published(db, slug)
    if not found:
        return {"status": "coming_soon", "slug": slug}
    return {"status": "published", **found[0]}
