"""Publishing channels beyond Instagram (agency M3). Module `marketing_studio`.

GET    /marketing/studio/channels                              Facebook Page + Google Business Profile connection state
GET    /marketing/studio/channels/{facebook|google}/oauth-start?token=   owner/manager: connect (a browser redirect)
GET    /marketing/studio/channels/{facebook|google}/oauth-callback       the provider redirects here (single-use state)
PUT    /marketing/studio/channels/facebook/page                choose which connected Page posts go to (owner)
PUT    /marketing/studio/channels/google/location              choose which Business Profile location (owner)
DELETE /marketing/studio/channels/{facebook|google}            owner: disconnect
PUT    /marketing/studio/content/{id}/targets                  which channels this post goes to (marketing.edit)
GET    /marketing/studio/guest-reviews                         Google reviews + reply state
POST   /marketing/studio/guest-reviews/sync                    fetch new reviews now (marketing.edit)
POST   /marketing/studio/guest-reviews/{id}/draft              ask the AI for a reply (queued; marketing.edit)
PUT    /marketing/studio/guest-reviews/{id}/draft              write or edit the reply (marketing.edit)
POST   /marketing/studio/guest-reviews/{id}/post               post the reply on Google (marketing.approve)
"""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.integration import Integration
from app.models.user import User
from app.services import marketing_channel_connections as conns
from app.services import marketing_channels as channels
from app.services import marketing_content_service as svc
from app.services.authz_service import require_capability

router = APIRouter(prefix="/marketing/studio", tags=["marketing-channels"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_owner = Depends(require_capability("settings.manage"))
_KINDS = {"facebook": conns.FB_KIND, "google": conns.GOOGLE_KIND}


def _err(exc: svc.MarketingError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _back(provider: str, status: str, reason: str = "") -> RedirectResponse:
    q = urlencode({"tab": "library", provider: status, **({"reason": reason[:120]} if reason else {})})
    return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/marketing/studio?{q}", status_code=302)


@router.get("/channels")
def get_channels(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return conns.status(db, user.tenant_id)


@router.get("/channels/{provider}/oauth-start")
def oauth_start(provider: str, token: str = Query(...), db: Session = Depends(get_db)):
    if provider not in _KINDS:
        raise HTTPException(status_code=404, detail="Unknown channel")
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not signed in")
    user = db.query(User).filter_by(id=decoded.get("sub"), is_active=True).first()
    role = getattr(getattr(user, "role", None), "value", getattr(user, "role", None))
    if user is None or role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Only an owner or manager can connect a channel")
    try:
        start = conns.facebook_start if provider == "facebook" else conns.google_start
        return RedirectResponse(start(user.tenant_id, user.id), status_code=302)
    except svc.MarketingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    except Exception:  # noqa: BLE001 -- no single-use state, no login
        raise HTTPException(status_code=503, detail="Login is unavailable right now (state store down)")


@router.get("/channels/{provider}/oauth-callback")
def oauth_callback(provider: str, code: str = Query(None), state: str = Query(None), error: str = Query(None),
                   db: Session = Depends(get_db)):
    if provider not in _KINDS:
        raise HTTPException(status_code=404, detail="Unknown channel")
    if error or not code or not state:
        return _back(provider, "error", error or "Login was cancelled.")
    try:
        if provider == "facebook":
            conns.facebook_finish(db, code, state)
        else:
            conns.google_finish(db, code, state)
    except svc.MarketingError as exc:
        db.rollback()
        return _back(provider, "error", exc.message)
    except Exception:  # noqa: BLE001
        db.rollback()
        return _back(provider, "error", "The login could not be finished. Try again.")
    db.commit()
    return _back(provider, "connected")


class PageIn(BaseModel):
    page_id: str = Field(min_length=1, max_length=64)


@router.put("/channels/facebook/page")
def choose_page(body: PageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_owner):
    try:
        conns.choose_page(db, user.tenant_id, body.page_id, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return conns.status(db, user.tenant_id)


class LocationIn(BaseModel):
    location: str = Field(min_length=1, max_length=200)


@router.put("/channels/google/location")
def choose_location(body: LocationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                    _m=_module, _c=_owner):
    try:
        conns.choose_location(db, user.tenant_id, body.location, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return conns.status(db, user.tenant_id)


@router.delete("/channels/{provider}")
def disconnect(provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_owner):
    if provider not in _KINDS:
        raise HTTPException(status_code=404, detail="Unknown channel")
    done = conns.disconnect(db, user.tenant_id, _KINDS[provider], user.id)
    db.commit()
    return {"disconnected": done}


class TargetsIn(BaseModel):
    targets: list[str] = Field(min_length=1, max_length=3)


@router.put("/content/{item_id}/targets")
def set_targets(item_id: str, body: TargetsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _m=_module, _c=_edit):
    from app.core.audit import append_audit
    try:
        item = svc.get_item(db, user.tenant_id, item_id)
    except svc.MarketingError as exc:
        raise _err(exc)
    allowed = channels.channels_for(item.kind)
    wanted = list(dict.fromkeys(body.targets))
    bad = [t for t in wanted if t not in allowed]
    if bad:
        raise _err(svc.MarketingError(422, "bad_channel", f"Can't post this {item.kind} to: {', '.join(bad)}."))
    connected = {"instagram"} | {c for c, kind in _KINDS.items()
                                 if db.query(Integration.id).filter_by(tenant_id=user.tenant_id, kind=kind, status="active").first()}
    missing = [t for t in wanted if t not in connected]
    if missing:
        raise _err(svc.MarketingError(409, "not_connected", f"Connect {', '.join(channels.LABEL[m] for m in missing)} first."))
    before = channels.targets_of(item)
    item.targets = wanted
    append_audit(db, tenant_id=user.tenant_id, action="marketing.content.targets", actor_user_id=user.id,
                 target_type="marketing_content", target_id=item.id, payload={"before": before, "after": wanted})
    db.commit()
    return {"targets": channels.targets_of(item)}


# ── Google reviews ──────────────────────────────────────────────────────────────────────────────────────────────────

_approve = Depends(require_capability("marketing.approve"))


@router.get("/guest-reviews")
def guest_reviews(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.services import marketing_guest_reviews as reviews
    return {"reviews": reviews.listing(db, user.tenant_id), "waiting": reviews.pending_count(db, user.tenant_id)}


@router.post("/guest-reviews/sync")
def guest_reviews_sync(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.adapters.instagram.publishing import PublishError
    from app.models.tenant import Tenant
    from app.services import marketing_guest_reviews as reviews
    try:
        out = reviews.sync(db, db.query(Tenant).filter_by(id=user.tenant_id).one())
    except PublishError as exc:
        db.rollback()
        raise HTTPException(status_code=503 if exc.transient else 409,
                            detail={"code": "google_error", "message": str(exc)[:300], "problems": []})
    db.commit()
    return out


@router.post("/guest-reviews/{review_id}/draft", status_code=202)
def guest_review_ai_draft(review_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                          _m=_module, _c=_edit):
    from app.services import marketing_guest_reviews as reviews
    from app.workers.tasks.marketing_studio import draft_review_reply
    try:
        row = reviews.get(db, user.tenant_id, review_id)
        if row.reply_status == "posted":
            raise svc.MarketingError(409, "already_replied", "This review already has a reply on Google.")
    except svc.MarketingError as exc:
        raise _err(exc)
    row.reply_status, row.reply_error = "drafting", None
    db.commit()
    try:
        draft_review_reply.delay(user.tenant_id, row.id)
    except Exception:  # noqa: BLE001
        row.reply_status, row.reply_error = "failed", "Background jobs are unavailable."
        db.commit()
    return {"id": row.id, "reply_status": row.reply_status}


class ReplyIn(BaseModel):
    text: str = Field(min_length=2, max_length=1000)


@router.put("/guest-reviews/{review_id}/draft")
def guest_review_edit(review_id: str, body: ReplyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                      _m=_module, _c=_edit):
    from app.services import marketing_guest_reviews as reviews
    try:
        row = reviews.edit_draft(db, user.tenant_id, review_id, body.text, user)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"id": row.id, "reply_status": row.reply_status, "reply_draft": row.reply_draft}


@router.post("/guest-reviews/{review_id}/post")
def guest_review_post(review_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                      _m=_module, _c=_approve):
    from app.models.tenant import Tenant
    from app.services import marketing_guest_reviews as reviews
    try:
        row = reviews.post(db, db.query(Tenant).filter_by(id=user.tenant_id).one(), review_id, user)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"id": row.id, "reply_status": row.reply_status, "reply_error": row.reply_error}
