"""Website builder phases 2-6 (staff API, /api/v1/websites/...): tracking + report (phase 2), promo codes (phase 4),
guides, Google reviews, video + Canva imports (phase 5), languages + launch report (phase 6).

Same module + capabilities as endpoints/website.py: read = website.read, settings that change what guests' browsers
load or what leaves HAIP = website.approve (owner/manager). Errors are {"detail": {"code", "message", "problems"}}.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.user import User
from app.schemas.website import PromoIn, TrackingIn
from app.services import website_blog, website_promos, website_report, website_reviews
from app.services import website_service as svc
from app.services import website_tracking as track
from app.services.authz_service import require_capability

router = APIRouter(prefix="/websites", tags=["website"])
_module = Depends(require_module("website"))
_read = Depends(require_capability("website.read"))
_edit = Depends(require_capability("website.edit"))
_approve = Depends(require_capability("website.approve"))


def _fail(exc: svc.WebsiteError):
    raise HTTPException(
        status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems}
    )


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


# ─── phase 2: measurement ─────────────────────────────────────────────────────────────────────────────


@router.get("/tracking")
def get_tracking(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    site = _site(db, user)
    return {**track.settings_out(site), "recent": track.recent(db, site)}


@router.put("/tracking")
def put_tracking(
    body: TrackingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve
):
    site = _site(db, user)
    if body.capi_enabled and not body.pixel_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "pixel_needed",
                "message": "Add the Meta Pixel (dataset) id before switching the Conversions API on.",
                "problems": [],
            },
        )
    out = track.update(db, site, body, actor_id=user.id)
    db.commit()
    _revalidate(user.tenant_id, site.id)
    return out


@router.get("/report")
def report(days: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.api.v1.endpoints.website import user_can_see_money
    from app.services.business_data_service import tenant_today

    site = _site(db, user)
    return website_report.build(
        db,
        site,
        today=tenant_today(db, user.tenant_id),
        days=max(7, min(days, 180)),
        show_money=user_can_see_money(db, user),
    )


# ─── phase 4: promo codes ─────────────────────────────────────────────────────────────────────────────


@router.get("/promos")
def list_promos(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return [website_promos.out(p) for p in website_promos.list_codes(db, user.tenant_id)]


@router.post("/promos", status_code=201)
def create_promo(
    body: PromoIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve
):
    try:
        p = website_promos.create(db, user.tenant_id, body, actor_id=user.id)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    _refresh_offer(db, user.tenant_id)
    return website_promos.out(p)


@router.put("/promos/{promo_id}")
def update_promo(
    promo_id: str,
    body: PromoIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _m=_module,
    _c=_approve,
):
    try:
        p = website_promos.update(db, user.tenant_id, promo_id, body, actor_id=user.id)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    _refresh_offer(db, user.tenant_id)
    return website_promos.out(p)


def _refresh_offer(db: Session, tenant_id: str) -> None:
    site = svc.get_site(db, tenant_id)
    if site is not None:
        _revalidate(tenant_id, site.id)  # an offer band may show this code


# ─── phase 5: guides (blog) ───────────────────────────────────────────────────────────────────────────
# A guide is a Marketing Studio item of kind "article" (website_blog): same versions and approval rules; the website
# shows only the approved version. These endpoints use the website capabilities so a workspace without Studio can run it.


class _Topic(BaseModel):
    topic: str = Field(min_length=4, max_length=160)


class _Seen(BaseModel):
    version_id: str = Field(max_length=64)


class _Article(BaseModel):
    payload: dict


def _mfail(exc: Exception):
    from app.services.marketing_content_service import MarketingError

    if isinstance(exc, MarketingError):
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems}
        )
    raise exc


def _article(db: Session, tenant_id: str, item_id: str):
    from app.models.marketing import MarketingContent

    item = db.query(MarketingContent).filter_by(id=item_id, tenant_id=tenant_id, kind="article").first()
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such guide.", "problems": []})
    return item


def _guide_out(db: Session, item) -> dict:
    from app.services import marketing_content_service as content_svc

    v = content_svc.get_version(db, item.tenant_id, item.current_version_id)
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "generation_status": item.generation_status,
        "generation_error": item.generation_error,
        "version_id": v.id if v else None,
        "payload": v.payload if v else None,
        "live": bool(item.approved_version_id and item.status == "approved"),
    }


@router.get("/blog")
def list_guides(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.models.marketing import MarketingContent

    rows = (
        db.query(MarketingContent)
        .filter(
            MarketingContent.tenant_id == user.tenant_id,
            MarketingContent.kind == "article",
            MarketingContent.status != "archived",
        )
        .order_by(MarketingContent.created_at.desc())
        .limit(100)
        .all()
    )
    return [_guide_out(db, r) for r in rows]


@router.post("/blog", status_code=202)
def write_guide(
    body: _Topic, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit
):
    from app.models.tenant import Tenant

    item = website_blog.request_draft(db, db.get(Tenant, user.tenant_id), body.topic, actor_id=user.id)
    db.commit()
    from app.workers.tasks.website import blog_draft

    blog_draft.delay(user.tenant_id, item.id, body.topic)
    return _guide_out(db, item)


@router.put("/blog/{item_id}")
def edit_guide(
    item_id: str,
    body: _Article,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _m=_module,
    _c=_edit,
):
    from app.services import marketing_content_service as content_svc

    item = _article(db, user.tenant_id, item_id)
    try:
        content_svc.add_version(db, user.tenant_id, item.id, body.payload, origin="human", actor_id=user.id)
    except Exception as exc:  # noqa: BLE001
        _mfail(exc)
    db.commit()
    _refresh_offer(db, user.tenant_id)  # an edit takes the approved version down until approved again
    return _guide_out(db, item)


@router.post("/blog/{item_id}/{action}")
def guide_action(
    item_id: str,
    action: str,
    body: _Seen,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _m=_module,
    _c=_edit,
):
    from app.services import marketing_content_service as content_svc
    from app.services.authz_service import has_capability

    item = _article(db, user.tenant_id, item_id)
    if action in ("approve", "reject", "archive") and not has_capability(db, user, "website.approve"):
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Only an owner or manager can do this.", "problems": []},
        )
    try:
        if action == "submit":
            content_svc.submit(db, user.tenant_id, item.id, body.version_id, user)
        elif action == "approve":
            content_svc.approve(db, user.tenant_id, item.id, body.version_id, user)
        elif action == "reject":
            content_svc.reject(db, user.tenant_id, item.id, body.version_id, user)
        elif action == "archive":
            content_svc.archive(db, user.tenant_id, item.id, user.id)
        else:
            raise HTTPException(
                status_code=404, detail={"code": "not_found", "message": "Unknown action.", "problems": []}
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _mfail(exc)
    db.commit()
    if action in ("approve", "archive"):
        _refresh_offer(db, user.tenant_id)
    db.refresh(item)
    return _guide_out(db, item)


# ─── phase 5: Google reviews on the site ─────────────────────────────────────────────────────────────


class _Consent(BaseModel):
    note: str | None = Field(None, max_length=300)  # how the guest agreed; None = take it off the website


@router.get("/reviews")
def list_reviews(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return website_reviews.listing(db, user.tenant_id)


@router.put("/reviews/{review_id}/consent")
def review_consent(
    review_id: str,
    body: _Consent,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _m=_module,
    _c=_approve,
):
    try:
        website_reviews.set_consent(db, user.tenant_id, review_id, note=body.note, actor_id=user.id)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    _refresh_offer(db, user.tenant_id)
    return website_reviews.listing(db, user.tenant_id)


@router.post("/reviews/import", status_code=202)
def import_reviews(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    from app.services.marketing_guest_reviews import tenants_with_google

    if user.tenant_id not in tenants_with_google(db):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "google_not_connected",
                "problems": [],
                "message": "Connect your Google Business Profile in Marketing › Studio › Settings first.",
            },
        )
    from app.workers.tasks.marketing_studio import reviews_sync_tenant

    reviews_sync_tenant.delay(user.tenant_id)
    return {"status": "queued"}


# ─── phase 5: video hero + Canva exports into the photo library ──────────────────────────────────────


def _video_out(a) -> dict:
    from app.services.media_storage import get_presigned_media_url

    return {
        "id": a.id,
        "ref": f"asset:{a.id}",
        "url": get_presigned_media_url(a.storage_key, expires_in=900),
        "alt_text": a.alt_text,
        "width": a.width,
        "height": a.height,
        "duration_ms": a.duration_ms,
        "mime_type": a.mime_type,
        "source": a.source,
        "provenance": a.provenance,
        "status": a.status,
    }


@router.get("/media/videos")
def list_videos(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.models.media_asset import MediaAsset

    rows = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.tenant_id == user.tenant_id, MediaAsset.status == "active", MediaAsset.mime_type == "video/mp4"
        )
        .order_by(MediaAsset.created_at.desc())
        .limit(100)
        .all()
    )
    return [_video_out(a) for a in rows]


@router.post("/media/import", status_code=201)
async def import_media(
    file: UploadFile = File(...),
    alt_text: str | None = Form(default=None, max_length=300),
    origin: str = Form(default="upload", pattern="^(upload|canva)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _m=_module,
    _c=_edit,
):
    """A PNG/JPG photo or an MP4 (video hero) into the library, e.g. a design exported from Canva. Photos are re-encoded
    by media_library_service; videos are probed and their sound + metadata stripped (marketing_reel.add_clip). No Canva
    account link: the owner downloads the export from Canva and uploads it here."""
    from app.services import marketing_reel as reel
    from app.services import media_library_service as media

    raw = await file.read(max(media.MAX_UPLOAD_BYTES, reel.MAX_CLIP_BYTES) + 1)
    is_mp4 = raw[4:8] == b"ftyp"
    try:
        asset = (
            reel.add_clip(db, user.tenant_id, raw, actor_id=user.id, alt_text=alt_text)
            if is_mp4
            else media.add_upload(db, user.tenant_id, raw, actor_id=user.id, alt_text=alt_text)
        )
    except media.MediaError as exc:
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": []}
        ) from exc
    if origin == "canva":
        asset.provenance = {**(asset.provenance or {}), "canva_export": True, "file_name": (file.filename or "")[:120]}
    append_audit_import(db, user, asset, origin)
    db.commit()
    return _video_out(asset)


def append_audit_import(db: Session, user: User, asset, origin: str) -> None:
    from app.core.audit import append_audit

    append_audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="website.media_imported",
        target_type="media_asset",
        target_id=asset.id,
        payload={"origin": origin, "mime_type": asset.mime_type},
    )


# ─── phase 6: languages ──────────────────────────────────────────────────────────────────────────────


class _Lang(BaseModel):
    language: str = Field(pattern="^[a-z]{2}$")


@router.get("/languages")
def languages(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.models.website import SiteVersion
    from app.schemas.site_spec import LANGUAGES

    site = _site(db, user)
    live = db.get(SiteVersion, site.live_version_id) if site.live_version_id else None
    on = set(((live.doc if live else {}) or {}).get("i18n") or {})
    return [{"code": k, "name": v, "live": k in on} for k, v in LANGUAGES.items()]


@router.post("/translate", status_code=202)
def translate(
    body: _Lang, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve
):
    from app.services import website_i18n

    site = _site(db, user)
    try:
        job = website_i18n.request(db, site, body.language, user)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    from app.workers.tasks.website import translate as task

    task.delay(user.tenant_id, job.id)
    return website_i18n.out(job)


@router.get("/translate/{job_id}")
def translate_job(
    job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read
):
    from app.services import website_i18n

    job = website_i18n.get_job(db, user.tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such job.", "problems": []})
    return website_i18n.out(job)


# ─── phase 6: launch report ──────────────────────────────────────────────────────────────────────────


@router.get("/launch-report")
def launch_report(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.models.tenant import Tenant
    from app.services import website_launch

    return website_launch.build(db, db.get(Tenant, user.tenant_id), _site(db, user))


@router.get("/launch-report.pdf")
def launch_report_pdf(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from fastapi.responses import Response

    from app.models.tenant import Tenant
    from app.services import website_launch

    tenant = db.get(Tenant, user.tenant_id)
    pdf = website_launch.render(
        website_launch.build(db, tenant, _site(db, user)), brand=tenant.brand_name or tenant.name
    )
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="website-launch-report.pdf"'},
    )
