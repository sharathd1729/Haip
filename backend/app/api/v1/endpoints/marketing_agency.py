"""Marketing agency API (plan phase A). Module `marketing_studio`; same capabilities as the Studio.

GET  /marketing/studio/agency                       team roster (role, level, effective level), kill switch, recent runs
PUT  /marketing/studio/agency                       owner: change role levels / pause (audited)
POST /marketing/studio/agency/run                   run the weekly cycle now (marketing.edit)
GET  /marketing/studio/approvals                    everything waiting for a person (content + AI images)
POST /marketing/studio/approvals/{type}/{id}/approve | reject     marketing.approve; delegates to the existing reviews
GET  /marketing/studio/content/{id}/preview         the images exactly as they would be posted (half size, data URLs)
POST /marketing/studio/content/{id}/pick-photos     fill empty photo slots from the library (new version, marketing.edit)
GET  /marketing/studio/content/{id}/review          brand review of the current text: checks (live) + AI editor advice
POST /marketing/studio/content/{id}/review          ask the AI editor again (queued; marketing.edit)
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_agency_run as runs
from app.services import marketing_agency_service as agency
from app.services import marketing_content_service as svc
from app.services import marketing_image_service as images
from app.services.authz_service import require_capability

router = APIRouter(prefix="/marketing/studio", tags=["marketing-agency"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_approve = Depends(require_capability("marketing.approve"))
_owner = Depends(require_capability("settings.manage"))


def _err(exc: svc.MarketingError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


@router.get("/agency")
def get_agency(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    tenant = _tenant(db, user)
    return {"paused": agency.get_agency(tenant)["paused"], "roster": agency.roster(tenant),
            "runs": runs.history(db, tenant.id), "schedule": "Mondays 09:00 (workspace time)",
            "pending_approvals": agency.pending_count(db, tenant.id)}


class AgencyUpdate(BaseModel):
    roles: Optional[dict[str, str]] = None
    paused: Optional[bool] = None


@router.put("/agency")
def put_agency(body: AgencyUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db),
               _m=_module, _c=_owner):
    tenant = _tenant(db, user)
    try:
        agency.update_agency(db, tenant, user.id, roles=body.roles, paused=body.paused)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"paused": agency.get_agency(tenant)["paused"], "roster": agency.roster(tenant)}


@router.post("/agency/run", status_code=202)
def run_now(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import agency_run_week

    if agency.get_agency(_tenant(db, user))["paused"]:
        raise HTTPException(status_code=409, detail={"code": "agency_paused",
                                                     "message": "The agency is paused. Resume it to run.", "problems": []})
    if runs.running(db, user.tenant_id) is not None:
        raise HTTPException(status_code=409, detail={"code": "run_in_progress", "message": "A run is already going.", "problems": []})
    try:
        agency_run_week.delay(user.tenant_id, "manual", user.id)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Background jobs are unavailable.",
                                                     "problems": []})
    return {"status": "queued"}


@router.get("/approvals")
def approvals(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    items = agency.pending_approvals(db, user.tenant_id)
    return {"count": len(items), "items": items}


class Review(BaseModel):
    version_id: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=500)


def _review(kind: str, item_id: str, body: Review, user: User, db: Session, approve: bool):
    try:
        if kind == "content":
            version_id = body.version_id or svc.get_item(db, user.tenant_id, item_id).current_version_id
            fn = svc.approve if approve else svc.reject
            fn(db, user.tenant_id, item_id, version_id, user, body.note)
            if approve:
                from app.services.marketing_publish_service import on_approved
                on_approved(db, _tenant(db, user), item_id)
        elif kind == "ai_image":
            images.review_image(db, user.tenant_id, item_id, user, approve=approve, note=body.note)
        else:
            raise HTTPException(status_code=404, detail={"code": "unknown_type", "message": "Unknown approval type.", "problems": []})
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"ok": True, "remaining": agency.pending_count(db, user.tenant_id)}


@router.post("/approvals/{kind}/{item_id}/approve")
def approve(kind: str, item_id: str, body: Review = Review(), user: User = Depends(get_current_user),
            db: Session = Depends(get_db), _m=_module, _c=_approve):
    return _review(kind, item_id, body, user, db, True)


@router.post("/approvals/{kind}/{item_id}/reject")
def reject(kind: str, item_id: str, body: Review = Review(), user: User = Depends(get_current_user),
           db: Session = Depends(get_db), _m=_module, _c=_approve):
    return _review(kind, item_id, body, user, db, False)


# ── Scheduling + publishing (plan phase C) ──────────────────────────────────────────────────────────────────────────

class ScheduleIn(BaseModel):
    scheduled_for: Optional[datetime] = None        # omitted = the suggested time


def _attempts(db: Session, tenant_id: str, item_id: str) -> list[dict]:
    from app.models.marketing import MarketingPublishAttempt
    rows = (db.query(MarketingPublishAttempt).filter_by(tenant_id=tenant_id, content_id=item_id)
            .order_by(MarketingPublishAttempt.created_at.desc()).all())
    return [{"id": a.id, "version_id": a.version_id, "status": a.status, "scheduled_for": a.scheduled_for, "tries": a.tries,
             "permalink": a.permalink, "error": a.error, "published_at": a.published_at, "channel": a.channel} for a in rows]


@router.get("/content/{item_id}/publishing")
def publishing(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.services import marketing_publish_service as pub
    try:
        item = svc.get_item(db, user.tenant_id, item_id)
    except svc.MarketingError as exc:
        raise _err(exc)
    from app.services import marketing_ai_service as ai
    from app.services import marketing_channels as channels
    tenant = _tenant(db, user)
    targets = channels.targets_of(item)
    problems, notes, previews = [], [], {}
    if item.status in ("approved", "scheduled"):
        try:
            payload = svc.approved_payload(db, user.tenant_id, item.id)
            for c in targets:
                p_, n_ = pub.preflight(db, user.tenant_id, item, payload, c)
                problems += [f"{channels.LABEL[c]}: {x}" if c != "instagram" else x for x in p_]
                notes += [f"{channels.LABEL[c]}: {x}" if c != "instagram" else x for x in n_]
                previews[c] = channels.preview(item.kind, payload, ai.get_profile(tenant), c)
        except svc.MarketingError as exc:
            problems = [exc.message]
    return {"status": item.status, "publish_level": agency.level(tenant, "publish"), "problems": sorted(set(problems)),
            "notes": notes, "targets": targets, "available_channels": list(channels.channels_for(item.kind)),
            "previews": previews, "suggested_time": pub.suggest_time(db, tenant).isoformat(),
            "attempts": _attempts(db, user.tenant_id, item.id)}


@router.post("/content/{item_id}/schedule")
def schedule(item_id: str, body: ScheduleIn = ScheduleIn(), user: User = Depends(get_current_user),
             db: Session = Depends(get_db), _m=_module, _c=_approve):
    from app.services import marketing_publish_service as pub
    tenant = _tenant(db, user)
    try:
        attempts = pub.schedule_all(db, tenant, item_id, body.scheduled_for or pub.suggest_time(db, tenant), user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"status": attempts[0].status, "scheduled_for": attempts[0].scheduled_for,
            "channels": [a.channel for a in attempts]}


@router.post("/content/{item_id}/unschedule")
def unschedule(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    from app.services import marketing_publish_service as pub
    try:
        pub.unschedule(db, user.tenant_id, item_id, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"ok": True}


@router.get("/content/{item_id}/preview")
def preview(item_id: str, version_id: Optional[str] = None, user: User = Depends(get_current_user),
            db: Session = Depends(get_db), _m=_module, _c=_read):
    """Drawn in memory from the version's payload with the same code the publisher uses; nothing is stored."""
    import base64

    from app.services import marketing_render as render
    from app.services.media_library_service import MediaError
    try:
        item = svc.get_item(db, user.tenant_id, item_id)
        version = svc.get_version(db, user.tenant_id, version_id or item.current_version_id)
    except svc.MarketingError as exc:
        raise _err(exc)
    if version is None or version.content_id != item.id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Version not found.", "problems": []})
    try:
        drawn = render.images(db, _tenant(db, user), item.kind, version.payload or {}, scale=0.5)
    except MediaError as exc:
        return {"version_id": version.id, "frames": [], "problems": [exc.message]}
    except Exception:  # noqa: BLE001  storage unreachable: say so rather than 500
        return {"version_id": version.id, "frames": [], "problems": ["The photos could not be loaded right now."]}
    return {"version_id": version.id, "problems": [], "frames": [
        {"src": "data:image/jpeg;base64," + base64.b64encode(data).decode(), "asset_id": src.id,
         "headline": f["headline"], "style": f["style"]} for data, src, f in drawn]}


@router.post("/content/{item_id}/pick-photos")
def pick_photos(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.services import marketing_photos as photos
    try:
        item = svc.get_item(db, user.tenant_id, item_id)
        if item.status not in ("draft", "rejected"):
            raise svc.MarketingError(409, "not_editable", "Only a draft can be changed; it is waiting for approval or posted.")
        filled = photos.attach_photos(db, _tenant(db, user), item.id, actor_id=user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"filled": filled, "version_id": svc.get_item(db, user.tenant_id, item_id).current_version_id}


@router.get("/content/{item_id}/review")
def get_review(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.services import marketing_review_service as review
    try:
        item = svc.get_item(db, user.tenant_id, item_id)
    except svc.MarketingError as exc:
        raise _err(exc)
    row = review.current(db, _tenant(db, user), item)
    db.commit()
    return review.as_dict(row)


@router.post("/content/{item_id}/review", status_code=202)
def request_review(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.services import marketing_review_service as review
    try:
        item = svc.get_item(db, user.tenant_id, item_id)
    except svc.MarketingError as exc:
        raise _err(exc)
    return review.as_dict(review.request_ai(db, _tenant(db, user), item))
