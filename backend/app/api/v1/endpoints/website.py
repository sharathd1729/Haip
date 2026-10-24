"""Website builder: staff API (/api/v1/websites). Module "website"; capabilities website.read / edit / approve.

Errors are {"detail": {"code", "message", "problems"}}. AI work is queued (Celery website.ai_job), never run here.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.inquiry import Inquiry, InquirySource
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import User
from app.models.website import BookingHold, SiteAiJob
from app.schemas.website import (
    AiGenerate,
    AiRequest,
    DomainAdd,
    DraftSave,
    SiteCreate,
    SiteSettings,
    SpecDraftIn,
    VersionAction,
)
from app.services import media_library_service as media
from app.services import website_ai_service as ai
from app.services import website_domain_service as dom
from app.services import website_public_service as pub
from app.services import website_service as svc
from app.services import website_spec_service as wspec
from app.services import website_version_service as vs
from app.services.authz_service import require_capability
from app.services.media_storage import get_presigned_media_url

router = APIRouter(prefix="/websites", tags=["website"])
_module = Depends(require_module("website"))
_read = Depends(require_capability("website.read"))
_edit = Depends(require_capability("website.edit"))
_approve = Depends(require_capability("website.approve"))
AI_JOBS_PER_HOUR = 20


def _fail(exc: Exception):
    if isinstance(exc, svc.WebsiteError):
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})
    if isinstance(exc, media.MediaError):
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": []})
    raise exc


def _site(db: Session, user: User):
    try:
        return svc.require_site(db, user.tenant_id)
    except svc.WebsiteError as exc:
        _fail(exc)


def _revalidate(tenant_id: str, site_id: str) -> None:
    try:
        from app.workers.tasks.website import revalidate
        revalidate.delay(tenant_id, site_id)
    except Exception:  # noqa: BLE001 -- pages refresh by themselves within 5 minutes
        pass


@router.get("/site")
def get_site(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    site = svc.get_site(db, user.tenant_id)
    if not site:
        raise HTTPException(status_code=404, detail={"code": "no_site", "message": "No website yet.", "problems": []})
    return svc.site_out(db, site)


@router.post("/site", status_code=201)
def create_site(body: SiteCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _m=_module, _c=_approve):
    tenant = db.get(Tenant, user.tenant_id)
    try:
        site = svc.create_site(db, tenant, actor_id=user.id, name=body.name, slug=body.slug)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return svc.site_out(db, site)


@router.put("/site/settings")
def update_settings(body: SiteSettings, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                    _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        svc.update_settings(db, user.tenant_id, site, body, actor_id=user.id)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    _revalidate(user.tenant_id, site.id)
    return svc.site_out(db, site)


@router.post("/site/{action}")
def pause_or_resume(action: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                    _m=_module, _c=_approve):
    if action not in ("pause", "resume"):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Not found", "problems": []})
    site = _site(db, user)
    vs.set_paused(db, site, action == "pause", user)
    db.commit()
    _revalidate(user.tenant_id, site.id)
    return svc.site_out(db, site)


def _draft_out(db: Session, site, v, problems=None) -> dict:
    return {"version": {"id": v.id, "number": v.number, "status": v.status, "sha256": v.sha256, "origin": v.origin,
                        "note": v.note, "updated_at": v.updated_at.isoformat() if v.updated_at else None},
            "doc": v.doc, "problems": problems or [], "checks": vs.checks(db, site, v.doc)}


@router.get("/draft")
def get_draft(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    site = _site(db, user)
    return _draft_out(db, site, vs.head(db, site))


@router.put("/draft")
def save_draft(body: DraftSave, user: User = Depends(get_current_user), db: Session = Depends(get_db),
               _m=_module, _c=_edit):
    site = _site(db, user)
    try:
        v, problems = vs.save_draft(db, site, body.doc, body.base_sha256, actor_id=user.id)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return _draft_out(db, site, v, problems)


@router.post("/draft/v2", status_code=201)
def create_v2_draft(body: SpecDraftIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                    _m=_module, _c=_approve):
    """A new draft version in the v2 builder format (SiteSpec), from a hand-written spec or the starter plan. The live site
    is untouched until this draft is approved and published like any other version."""
    site = _site(db, user)
    tenant = db.get(Tenant, user.tenant_id)
    head_doc = vs.head(db, site).doc if site.draft_version_id else {}
    spec = body.spec if body.spec is not None else wspec.starter(tenant, (head_doc or {}).get("site"))
    try:
        v, problems = wspec.create_draft(db, site, spec, actor_id=user.id, origin="seed" if body.seed else "human")
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return _draft_out(db, site, v, problems)


@router.get("/live-data")
def live_data(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    """What the editor canvas needs to render live sections exactly as guests will see them (stays, policies, photos)."""
    site = _site(db, user)
    tenant = db.get(Tenant, user.tenant_id)
    data = pub.bootstrap(db, tenant, site, vs.head(db, site), preview=True)
    data["preview_url"] = None
    return data


@router.get("/versions")
def versions(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return vs.history(db, _site(db, user))


@router.get("/versions/{version_id}")
def version(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    site = _site(db, user)
    try:
        v = vs.get_version(db, site, version_id)
    except svc.WebsiteError as exc:
        _fail(exc)
    return {"id": v.id, "number": v.number, "status": v.status, "sha256": v.sha256, "doc": v.doc, "note": v.note}


@router.post("/versions/{version_id}/submit")
def submit(version_id: str, body: Optional[VersionAction] = None, user: User = Depends(get_current_user),
           db: Session = Depends(get_db), _m=_module, _c=_edit):
    site = _site(db, user)
    try:
        v = vs.submit(db, site, version_id, user, note=body.note if body else None)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    try:
        from app.services import push_service
        push_service.send_to_tenant(db, user.tenant_id, "Website changes to approve",
                                    f"Version {v.number} of the website is waiting for approval.",
                                    url="/dashboard/marketing/website", tag="website-review")
    except Exception:  # noqa: BLE001 -- push is best-effort
        pass
    return svc.site_out(db, site)


@router.post("/versions/{version_id}/publish")
def publish(version_id: str, body: Optional[VersionAction] = None, user: User = Depends(get_current_user),
            db: Session = Depends(get_db), _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        vs.publish(db, site, version_id, user)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    _revalidate(user.tenant_id, site.id)
    return svc.site_out(db, site)


@router.post("/versions/{version_id}/reject")
def reject(version_id: str, body: Optional[VersionAction] = None, user: User = Depends(get_current_user),
           db: Session = Depends(get_db), _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        vs.reject(db, site, version_id, user, body.note if body else None)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return svc.site_out(db, site)


@router.post("/versions/{version_id}/restore")
def restore(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
            _m=_module, _c=_edit):
    site = _site(db, user)
    try:
        v = vs.restore(db, site, version_id, user)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return _draft_out(db, site, v)


@router.get("/preview-link")
def preview_link(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    site = _site(db, user)
    token = pub.preview_token(site, vs.head(db, site))
    return {"url": f"https://{svc.primary_host(db, site)}/_haip/preview/{token}", "expires_in_hours": 24}


# ─── domains ────────────────────────────────────────────────────────────────────────────────────────────

@router.post("/domains", status_code=201)
def add_domain(body: DomainAdd, user: User = Depends(get_current_user), db: Session = Depends(get_db),
               _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        dom.add(db, site, body.hostname, actor_id=user.id)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return svc.site_out(db, site)


@router.post("/domains/{domain_id}/verify")
def verify_domain(domain_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  _m=_module, _c=_approve):
    from app.models.website import SiteDomain
    site = _site(db, user)
    d = db.query(SiteDomain).filter_by(id=domain_id, site_id=site.id, tenant_id=user.tenant_id).first()
    if not d:
        raise HTTPException(status_code=404, detail={"code": "domain_not_found", "message": "Not found", "problems": []})
    dom.verify(db, d, actor_id=user.id)
    db.commit()
    return svc.site_out(db, site)


@router.delete("/domains/{domain_id}")
def remove_domain(domain_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        dom.remove(db, site, domain_id, actor_id=user.id)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return svc.site_out(db, site)


# ─── AI developer ───────────────────────────────────────────────────────────────────────────────────────

def _queue_job(db: Session, user: User, site, kind: str, text: Optional[str]) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.query(func.count(SiteAiJob.id)).filter(SiteAiJob.tenant_id == user.tenant_id, SiteAiJob.created_at >= since).scalar()
    if (recent or 0) >= AI_JOBS_PER_HOUR:
        raise HTTPException(status_code=429, detail={"code": "ai_busy", "message": "That's a lot of requests this hour. Try again shortly.", "problems": []})
    if site.draft_version_id and wspec.is_v2(vs.head(db, site).doc):
        raise HTTPException(status_code=409, detail={"code": "ai_classic_only", "message": "The AI developer edits classic "
                            "sites. The new builder's AI arrives in a later phase.", "problems": []})
    running = db.query(SiteAiJob.id).filter(SiteAiJob.site_id == site.id, SiteAiJob.status.in_(("pending", "running")),
                                            SiteAiJob.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10)).first()
    if running:
        raise HTTPException(status_code=409, detail={"code": "ai_running", "message": "The AI developer is still working on your last request.", "problems": []})
    job = SiteAiJob(tenant_id=user.tenant_id, site_id=site.id, kind=kind, request=text, status="pending",
                    base_version_id=site.draft_version_id, created_by=user.id)
    db.add(job)
    db.commit()
    try:
        from app.workers.tasks.website import ai_job
        ai_job.delay(user.tenant_id, job.id)
    except Exception:  # noqa: BLE001
        ai.mark_failed(db, user.tenant_id, job.id, "The AI developer couldn't be started. Try again.")
        db.commit()
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "The AI developer couldn't be started. Try again.", "problems": []})
    return ai.job_out(job)


@router.post("/ai/edit", status_code=202)
def ai_edit(body: AiRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db),
            _m=_module, _c=_edit):
    return _queue_job(db, user, _site(db, user), "edit", body.message)


@router.post("/ai/generate", status_code=202)
def ai_generate(body: AiGenerate, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _m=_module, _c=_edit):
    return _queue_job(db, user, _site(db, user), "generate", body.brief)


@router.get("/ai/jobs")
def ai_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    site = _site(db, user)
    rows = (db.query(SiteAiJob).filter_by(tenant_id=user.tenant_id, site_id=site.id)
            .order_by(SiteAiJob.created_at.desc()).limit(30).all())
    return [ai.job_out(j) for j in rows]


@router.get("/ai/jobs/{job_id}")
def ai_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    job = db.query(SiteAiJob).filter_by(id=job_id, tenant_id=user.tenant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Not found", "problems": []})
    return ai.job_out(job)


# ─── photos ─────────────────────────────────────────────────────────────────────────────────────────────

def _asset_out(a: MediaAsset) -> dict:
    return {"id": a.id, "ref": f"asset:{a.id}", "url": get_presigned_media_url(a.storage_key, expires_in=900),
            "alt_text": a.alt_text, "width": a.width, "height": a.height, "source": a.source, "status": a.status}


@router.get("/media")
def list_media(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    rows = (db.query(MediaAsset).filter(MediaAsset.tenant_id == user.tenant_id, MediaAsset.status == "active")
            .order_by(MediaAsset.created_at.desc()).limit(300).all())
    return [_asset_out(a) for a in rows]


@router.post("/media", status_code=201)
async def upload_media(file: UploadFile = File(...), alt_text: Optional[str] = Form(default=None, max_length=300),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    raw = await file.read(media.MAX_UPLOAD_BYTES + 1)
    try:
        asset = media.add_upload(db, user.tenant_id, raw, actor_id=user.id, alt_text=alt_text)
    except media.MediaError as exc:
        _fail(exc)
    db.commit()
    return _asset_out(asset)


# ─── results ────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/analytics")
def analytics(days: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db),
              _m=_module, _c=_read):
    from app.services.business_data_service import tenant_today
    site = _site(db, user)
    days = max(7, min(days, 90))
    today = tenant_today(db, user.tenant_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    views = pub.views_summary(db, site, today, days)
    leads = db.query(func.count(Inquiry.id)).filter(Inquiry.tenant_id == user.tenant_id, Inquiry.source == InquirySource.WEBSITE,
                                                    Inquiry.created_at >= since).scalar() or 0
    holds = db.query(BookingHold.status, func.count(BookingHold.id), func.coalesce(func.sum(BookingHold.total), 0)).filter(
        BookingHold.tenant_id == user.tenant_id, BookingHold.site_id == site.id, BookingHold.created_at >= since
    ).group_by(BookingHold.status).all()
    by_status = {s: {"count": int(c), "value": str(v)} for s, c, v in holds}
    show_money = user_can_see_money(db, user)
    if not show_money:
        by_status = {s: {"count": d["count"]} for s, d in by_status.items()}
    return {"days": days, "views": views, "website_leads": int(leads), "bookings": by_status,
            "money_restricted": not show_money}


def user_can_see_money(db: Session, user: User) -> bool:
    from app.services.authz_service import has_capability
    try:
        return bool(has_capability(db, user, "bookings.read"))
    except Exception:  # noqa: BLE001
        return False
