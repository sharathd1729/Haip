"""Marketing Studio API (docs/marketing-website/PHASE0_AUDIT.md §7.3). Module `marketing_studio`; capabilities
marketing.read / marketing.edit / marketing.approve. Nothing here publishes externally (Phase 4).

GET  /marketing/studio/profile                  PUT same          business profile (brand_config.business_profile)
GET  /marketing/studio/measured                                    latest measured Instagram numbers (provider data)
POST /marketing/studio/audits   GET  .../audits[/{id}]             social audit = measured snapshot + AI assessment
POST /marketing/studio/plans    GET  .../plans[/{id}]              strategy + content calendar
POST /marketing/studio/plans/{id}/content                          draft items for the plan's calendar entries
GET  /marketing/studio/content  POST same                          content items
GET  /marketing/studio/content/{id}                                item + current/approved version + history
POST /marketing/studio/content/{id}/versions                       save an edit (new version; voids an approval)
POST /marketing/studio/content/{id}/generate                       AI writes a new version (async)
POST /marketing/studio/content/{id}/submit | approve | reject | archive
GET  /marketing/studio/media    POST same (multipart)              media library
POST /marketing/studio/media/{id}/render   GET .../templates        template creative from a library photo
GET  /marketing/studio/usage                                       metered usage for this module
GET  /marketing/studio/settings   PUT same (owner)                 opt-in switches (AI images)
GET  /marketing/studio/image-models                                models with licence status (blocked ones say why)
POST /marketing/studio/images     GET same                         AI image jobs (async; result needs approval)
POST /marketing/studio/media/{id}/approve | reject                 review an AI image (marketing.approve)
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.marketing import MarketingAudit, MarketingContent, MarketingImageJob, MarketingPlan
from app.models.media_asset import MediaAsset
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.usage_event import UsageEvent
from app.models.user import User
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as svc
from app.services import marketing_image_service as images
from app.services import media_library_service as media
from app.services.authz_service import require_capability
from app.services.media_storage import get_presigned_media_url

log = structlog.get_logger()
router = APIRouter(prefix="/marketing/studio", tags=["marketing-studio"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_approve = Depends(require_capability("marketing.approve"))
_owner_settings = Depends(require_capability("settings.manage"))
MAX_PLAN_DAYS = 62


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.MarketingError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})
    except media.MediaError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": []})


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


def _check_property(db: Session, tenant_id: str, property_id: Optional[str]) -> None:
    if property_id and db.query(Property.id).filter_by(id=property_id, tenant_id=tenant_id).first() is None:
        raise HTTPException(status_code=404, detail={"code": "property_not_found", "message": "No such property.", "problems": []})


def _queue(db: Session, task, model, row_id: str, tenant_id: str, *args) -> None:
    """Queue after commit. If the broker is down, record the failure instead of leaving the row pending forever."""
    try:
        task.delay(tenant_id, row_id, *args)
    except Exception as exc:  # noqa: BLE001
        log.error("marketing_queue_failed", row_id=row_id, error=str(exc))
        ai.mark_failed(db, model, row_id, tenant_id, "Could not start the AI job (queue unavailable). Try again.")
        db.commit()
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Background jobs are unavailable.", "problems": []})


# ── Profile + measured data ─────────────────────────────────────────────────────────────────────────────────────────

@router.get("/profile")
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    tenant = _tenant(db, user)
    return {"brand_name": tenant.brand_name or tenant.name, "profile": ai.get_profile(tenant)}


@router.put("/profile")
def put_profile(body: dict[str, Any], user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    tenant = _tenant(db, user)
    try:
        clean = ai.put_profile(db, tenant, body, user.id)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_profile", "message": "Some fields are not valid.",
                                                     "problems": [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]})
    db.commit()
    return {"brand_name": tenant.brand_name or tenant.name, "profile": clean}


@router.get("/measured")
def measured(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return ai.measured_snapshot(db, user.tenant_id)


# ── Audits ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _audit_out(a: MarketingAudit) -> dict:
    return {"id": a.id, "status": a.status, "error": a.error, "measured": a.measured, "assessment": a.assessment,
            "prompt_version": a.prompt_version, "model": a.model, "created_at": a.created_at, "created_by": a.created_by}


@router.post("/audits", status_code=202)
def create_audit(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import generate_audit

    audit = MarketingAudit(tenant_id=user.tenant_id, measured=ai.measured_snapshot(db, user.tenant_id), status="pending",
                           created_by=user.id)
    db.add(audit)
    db.commit()
    _queue(db, generate_audit, MarketingAudit, audit.id, user.tenant_id)
    return _audit_out(audit)


@router.get("/audits")
def list_audits(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    rows = (db.query(MarketingAudit).filter_by(tenant_id=user.tenant_id)
            .order_by(MarketingAudit.created_at.desc()).limit(20).all())
    return [_audit_out(a) for a in rows]


@router.get("/audits/{audit_id}")
def get_audit(audit_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    a = db.query(MarketingAudit).filter_by(id=audit_id, tenant_id=user.tenant_id).first()
    if a is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such audit.", "problems": []})
    return _audit_out(a)


# ── Plans ───────────────────────────────────────────────────────────────────────────────────────────────────────────

class PlanCreate(BaseModel):
    period_start: date
    period_end: date
    brief: Optional[str] = Field(default=None, max_length=2000)
    audit_id: Optional[str] = None


def _plan_out(p: MarketingPlan) -> dict:
    return {"id": p.id, "status": p.status, "error": p.error, "period_start": p.period_start, "period_end": p.period_end,
            "brief": p.brief, "body": p.body, "audit_id": p.audit_id, "prompt_version": p.prompt_version, "model": p.model,
            "created_at": p.created_at}


@router.post("/plans", status_code=202)
def create_plan(body: PlanCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import generate_plan

    days = (body.period_end - body.period_start).days
    if days < 0 or days >= MAX_PLAN_DAYS:
        raise HTTPException(status_code=422, detail={"code": "bad_period", "problems": [],
                                                     "message": f"The period must run forwards and be at most {MAX_PLAN_DAYS} days."})
    if body.audit_id and db.query(MarketingAudit.id).filter_by(id=body.audit_id, tenant_id=user.tenant_id).first() is None:
        raise HTTPException(status_code=404, detail={"code": "audit_not_found", "message": "No such audit.", "problems": []})
    plan = MarketingPlan(tenant_id=user.tenant_id, period_start=body.period_start.isoformat(),
                         period_end=body.period_end.isoformat(), brief=body.brief, audit_id=body.audit_id,
                         status="pending", created_by=user.id)
    db.add(plan)
    db.commit()
    _queue(db, generate_plan, MarketingPlan, plan.id, user.tenant_id)
    return _plan_out(plan)


@router.get("/plans")
def list_plans(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    rows = db.query(MarketingPlan).filter_by(tenant_id=user.tenant_id).order_by(MarketingPlan.created_at.desc()).limit(20).all()
    return [_plan_out(p) for p in rows]


def _plan_or_404(db: Session, tenant_id: str, plan_id: str) -> MarketingPlan:
    p = db.query(MarketingPlan).filter_by(id=plan_id, tenant_id=tenant_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such plan.", "problems": []})
    return p


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return _plan_out(_plan_or_404(db, user.tenant_id, plan_id))


@router.post("/plans/{plan_id}/content", status_code=201)
def content_from_plan(plan_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    """One empty draft item per calendar entry. Re-running skips entries that already have an item."""
    plan = _plan_or_404(db, user.tenant_id, plan_id)
    if plan.status != "ready":
        raise HTTPException(status_code=409, detail={"code": "plan_not_ready", "message": "The plan is not ready.", "problems": []})
    have = {(c.planned_for, c.kind, c.title) for c in db.query(MarketingContent).filter_by(tenant_id=user.tenant_id, plan_id=plan.id)}
    created = []
    for e in (plan.body or {}).get("calendar", []):
        title = f"{e['pillar']}: {e['idea']}"[:160]
        if (e["date"], e["kind"], title) in have:
            continue
        created.append(svc.create_item(db, user.tenant_id, kind=e["kind"], title=title, actor_id=user.id,
                                       plan_id=plan.id, planned_for=e["date"]))
    db.commit()
    return {"created": len(created), "ids": [c.id for c in created]}


# ── Content ─────────────────────────────────────────────────────────────────────────────────────────────────────────

class ContentCreate(BaseModel):
    kind: str
    title: str = Field(min_length=1, max_length=160)
    payload: Optional[dict[str, Any]] = None
    property_id: Optional[str] = None
    planned_for: Optional[date] = None


class VersionCreate(BaseModel):
    payload: dict[str, Any]
    note: Optional[str] = Field(default=None, max_length=500)


class GenerateRequest(BaseModel):
    brief: Optional[str] = Field(default=None, max_length=1000)


class Decision(BaseModel):
    version_id: str
    note: Optional[str] = Field(default=None, max_length=500)


def _version_out(v) -> Optional[dict]:
    if v is None:
        return None
    return {"id": v.id, "version": v.version, "payload": v.payload, "sha256": v.sha256, "origin": v.origin, "note": v.note,
            "prompt_version": v.prompt_version, "model": v.model, "created_by": v.created_by, "created_at": v.created_at}


def _item_out(db: Session, item: MarketingContent, *, full: bool = False) -> dict:
    out = {"id": item.id, "kind": item.kind, "channel": item.channel, "title": item.title, "status": item.status,
           "property_id": item.property_id, "plan_id": item.plan_id, "planned_for": item.planned_for,
           "current_version_id": item.current_version_id, "approved_version_id": item.approved_version_id,
           "generation_status": item.generation_status, "generation_error": item.generation_error,
           "created_by": item.created_by, "created_at": item.created_at, "updated_at": item.updated_at}
    if full:
        h = svc.history(db, item.tenant_id, item.id)
        out["current"] = _version_out(svc.get_version(db, item.tenant_id, item.current_version_id))
        out["versions"] = [_version_out(v) for v in h["versions"]]
        out["decisions"] = [{"id": d.id, "version_id": d.version_id, "decision": d.decision, "note": d.note,
                             "actor_user_id": d.actor_user_id, "created_at": d.created_at} for d in h["decisions"]]
    return out


@router.get("/content")
def list_content(status: Optional[str] = Query(None), user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 _m=_module, _c=_read):
    q = db.query(MarketingContent).filter(MarketingContent.tenant_id == user.tenant_id)
    q = q.filter(MarketingContent.status == status) if status else q.filter(MarketingContent.status != "archived")
    return [_item_out(db, i) for i in q.order_by(MarketingContent.updated_at.desc()).limit(200).all()]


@router.post("/content", status_code=201)
def create_content(body: ContentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    _check_property(db, user.tenant_id, body.property_id)
    item = _run(svc.create_item, db, user.tenant_id, kind=body.kind, title=body.title, actor_id=user.id, payload=body.payload,
                property_id=body.property_id, planned_for=body.planned_for.isoformat() if body.planned_for else None)
    db.commit()
    return _item_out(db, item, full=True)


@router.get("/content/{item_id}")
def get_content(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return _item_out(db, _run(svc.get_item, db, user.tenant_id, item_id), full=True)


@router.post("/content/{item_id}/versions", status_code=201)
def add_version(item_id: str, body: VersionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _m=_module, _c=_edit):
    _run(svc.add_version, db, user.tenant_id, item_id, body.payload, origin="human", actor_id=user.id, note=body.note)
    db.commit()
    return _item_out(db, _run(svc.get_item, db, user.tenant_id, item_id), full=True)


@router.post("/content/{item_id}/generate", status_code=202)
def generate(item_id: str, body: GenerateRequest = GenerateRequest(), user: User = Depends(get_current_user),
             db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import generate_content

    item = _run(svc.get_item, db, user.tenant_id, item_id)
    if item.status == "archived":
        raise HTTPException(status_code=409, detail={"code": "archived", "message": "Archived content cannot change.", "problems": []})
    n = (db.query(MarketingContent)
         .filter(MarketingContent.id == item.id, MarketingContent.tenant_id == user.tenant_id,
                 MarketingContent.generation_status != "pending")
         .update({"generation_status": "pending", "generation_error": None}, synchronize_session=False))
    if n != 1:
        raise HTTPException(status_code=409, detail={"code": "generation_in_progress", "message": "Already generating.", "problems": []})
    db.commit()
    _queue(db, generate_content, MarketingContent, item.id, user.tenant_id, user.id, body.brief or "")
    db.refresh(item)
    return _item_out(db, item)


@router.post("/content/{item_id}/submit")
def submit(item_id: str, body: Decision, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    item = _run(svc.submit, db, user.tenant_id, item_id, body.version_id, user)
    db.commit()
    from app.services.marketing_agency_service import notify_needs_approval
    notify_needs_approval(db, user.tenant_id, "Marketing: approval needed", f"“{item.title}” is waiting for approval.")
    return _item_out(db, item, full=True)


@router.post("/content/{item_id}/approve")
def approve(item_id: str, body: Decision, user: User = Depends(get_current_user), db: Session = Depends(get_db),
            _m=_module, _c=_approve):
    item = _run(svc.approve, db, user.tenant_id, item_id, body.version_id, user, body.note)
    from app.services.marketing_publish_service import on_approved
    on_approved(db, _tenant(db, user), item.id)
    db.commit()
    db.refresh(item)
    return _item_out(db, item, full=True)


@router.post("/content/{item_id}/reject")
def reject(item_id: str, body: Decision, user: User = Depends(get_current_user), db: Session = Depends(get_db),
           _m=_module, _c=_approve):
    item = _run(svc.reject, db, user.tenant_id, item_id, body.version_id, user, body.note)
    db.commit()
    return _item_out(db, item, full=True)


@router.post("/content/{item_id}/archive")
def archive(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    item = _run(svc.archive, db, user.tenant_id, item_id, user.id)
    db.commit()
    return _item_out(db, item)


# ── Media ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _asset_out(a: MediaAsset) -> dict:
    return {"id": a.id, "url": get_presigned_media_url(a.storage_key, expires_in=900), "mime_type": a.mime_type, "status": a.status,
            "created_by": a.created_by,
            "width": a.width, "height": a.height, "bytes": a.bytes, "alt_text": a.alt_text, "source": a.source,
            "provenance": a.provenance, "property_id": a.property_id, "created_at": a.created_at}


@router.get("/media")
def list_media(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    rows = (db.query(MediaAsset).filter(MediaAsset.tenant_id == user.tenant_id, MediaAsset.status.in_(("active", "pending_review")))
            .order_by(MediaAsset.created_at.desc()).limit(200).all())
    return [_asset_out(a) for a in rows]


@router.post("/media", status_code=201)
async def upload_media(file: UploadFile = File(...), alt_text: Optional[str] = Form(default=None, max_length=300),
                       property_id: Optional[str] = Form(default=None), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db), _m=_module, _c=_edit):
    _check_property(db, user.tenant_id, property_id)
    raw = await file.read(media.MAX_UPLOAD_BYTES + 1)
    asset = _run(media.add_upload, db, user.tenant_id, raw, actor_id=user.id, alt_text=alt_text, property_id=property_id)
    db.commit()
    return _asset_out(asset)


@router.get("/templates")
def templates(_m=_module, _c=_read):
    return [{"key": k, "label": v["label"], "width": v["size"][0], "height": v["size"][1]} for k, v in media.TEMPLATES.items()]


class RenderRequest(BaseModel):
    template: str
    headline: str = Field(min_length=1, max_length=80)
    subline: Optional[str] = Field(default=None, max_length=120)


@router.post("/media/{asset_id}/render", status_code=201)
def render(asset_id: str, body: RenderRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db),
           _m=_module, _c=_edit):
    tenant = _tenant(db, user)
    problems = svc.check_text(db, user.tenant_id, {"headline": body.headline, "subline": body.subline or ""})
    if problems:
        raise HTTPException(status_code=422, detail={"code": "content_not_allowed", "message": "The text breaks a workspace rule.",
                                                     "problems": problems})
    asset = _run(media.render_creative, db, tenant, asset_id, template=body.template, headline=body.headline,
                 subline=body.subline, actor_id=user.id)
    db.commit()
    return _asset_out(asset)


# ── Usage ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=366), user: User = Depends(get_current_user), db: Session = Depends(get_db),
          _m=_module, _c=_read):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (db.query(UsageEvent.kind, func.count(UsageEvent.id), func.coalesce(func.sum(UsageEvent.units), 0))
            .filter(UsageEvent.tenant_id == user.tenant_id, UsageEvent.module == "marketing_studio", UsageEvent.created_at >= since)
            .group_by(UsageEvent.kind).all())
    return {"days": days, "since": since.isoformat(), "by_kind": [{"kind": k, "events": n, "units": int(u)} for k, n, u in rows]}


# ── AI images (opt-in) ──────────────────────────────────────────────────────────────────────────────────────────────

class StudioSettings(BaseModel):
    ai_images_enabled: Optional[bool] = None
    ai_images_monthly_cap: Optional[int] = Field(default=None, ge=0, le=images.MAX_MONTHLY_CAP)


def _settings_out(db: Session, tenant: Tenant) -> dict:
    return {"ai_images_enabled": images.ai_images_enabled(tenant), "ai_images_monthly_cap": images.monthly_cap(tenant),
            "ai_images_used_this_month": images.used_this_month(db, tenant), "default_model": images.image_adapter.DEFAULT_MODEL}


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return _settings_out(db, _tenant(db, user))


@router.put("/settings")
def put_settings(body: StudioSettings, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 _m=_module, _c=_owner_settings):
    tenant = _tenant(db, user)
    if body.ai_images_enabled is not None:
        images.set_ai_images(db, tenant, body.ai_images_enabled, user.id)
    if body.ai_images_monthly_cap is not None:
        _run(images.set_monthly_cap, db, tenant, body.ai_images_monthly_cap, user.id)
    db.commit()
    return _settings_out(db, tenant)


@router.get("/image-models")
def image_models(_m=_module, _c=_read):
    return images.models_catalogue()


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=images.PROMPT_MAX)
    model: str = "gemini-3.1-flash-lite-image"
    shape: str = "portrait"
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)


def _job_out(j: MarketingImageJob) -> dict:
    return {"id": j.id, "prompt": j.prompt, "model": j.model, "shape": j.shape, "status": j.status, "error": j.error,
            "asset_id": j.asset_id, "created_by": j.created_by, "created_at": j.created_at}


@router.post("/images", status_code=202)
def request_image(body: ImageRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import generate_image

    job = _run(images.request_image, db, _tenant(db, user), prompt=body.prompt, model=body.model, shape=body.shape,
               actor_id=user.id, seed=body.seed)
    db.commit()
    _queue(db, generate_image, MarketingImageJob, job.id, user.tenant_id)
    return _job_out(job)


@router.get("/images")
def list_images(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    rows = (db.query(MarketingImageJob).filter_by(tenant_id=user.tenant_id)
            .order_by(MarketingImageJob.created_at.desc()).limit(50).all())
    return [_job_out(j) for j in rows]


class ReviewNote(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/media/{asset_id}/approve")
def approve_image(asset_id: str, body: ReviewNote = ReviewNote(), user: User = Depends(get_current_user),
                  db: Session = Depends(get_db), _m=_module, _c=_approve):
    asset = _run(images.review_image, db, user.tenant_id, asset_id, user, approve=True, note=body.note)
    db.commit()
    return _asset_out(asset)


@router.post("/media/{asset_id}/reject")
def reject_image(asset_id: str, body: ReviewNote = ReviewNote(), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db), _m=_module, _c=_approve):
    asset = _run(images.review_image, db, user.tenant_id, asset_id, user, approve=False, note=body.note)
    db.commit()
    return _asset_out(asset)
