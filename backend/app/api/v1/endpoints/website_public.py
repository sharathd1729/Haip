"""Website builder: guest-facing API used by the sites renderer (/api/v1/public/sites/{host}/...).

No login. The tenant comes only from the hostname (website_host_lookup) or a signed preview token, never from the
request body. Per-IP limits live in middleware/rate_limit.py (_CLIENT_SITE_*). Prices are computed server-side.
"""
import hashlib
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas.website import EnquiryIn, HoldIn, ManageLookupIn, PageViewIn, QuoteIn
from app.services import website_booking_service as book
from app.services import website_public_service as pub
from app.services.website_leads import enquiry as make_enquiry
from app.services.website_service import WebsiteError, site_settings

router = APIRouter(prefix="/public", tags=["website-public"])


def _fail(exc: WebsiteError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _ip_hash(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    return hashlib.sha256(f"{settings.SECRET_KEY[:16]}:{ip}".encode()).hexdigest()[:32] if ip else None


def _resolve(db: Session, host: str):
    try:
        return pub.resolve_host(db, host)
    except WebsiteError as exc:
        _fail(exc)


def _live(db: Session, host: str):
    tenant, site = _resolve(db, host)
    try:
        return tenant, site, pub.require_live(db, site)
    except WebsiteError as exc:
        _fail(exc)


@router.get("/sites/{host}/bootstrap")
def bootstrap(host: str, db: Session = Depends(get_db)):
    tenant, site, v = _live(db, host)
    return pub.bootstrap(db, tenant, site, v)


@router.get("/preview/{token}/bootstrap")
def preview_bootstrap(token: str, db: Session = Depends(get_db)):
    try:
        tenant, site, v = pub.read_preview(db, token)
    except WebsiteError as exc:
        _fail(exc)
    return pub.bootstrap(db, tenant, site, v, preview=True)


@router.get("/sites/{host}/stays/{slug}")
def stay(host: str, slug: str, db: Session = Depends(get_db)):
    tenant, site, _ = _live(db, host)
    try:
        return pub.stay_detail(db, tenant, site, slug)
    except WebsiteError as exc:
        _fail(exc)


@router.get("/preview/{token}/stays/{slug}")
def preview_stay(token: str, slug: str, db: Session = Depends(get_db)):
    try:
        tenant, site, _ = pub.read_preview(db, token)
        return pub.stay_detail(db, tenant, site, slug)
    except WebsiteError as exc:
        _fail(exc)


@router.get("/sites/{host}/availability")
def availability(host: str, property_id: str = Query(..., max_length=64), start: Optional[date] = None,
                 days: int = Query(62, ge=1, le=120), db: Session = Depends(get_db)):
    tenant, site, _ = _live(db, host)
    try:
        prop = book.property_for(db, site, property_id)
    except WebsiteError as exc:
        _fail(exc)
    today = book.today_for(db, tenant.id)
    first = max(start or today, today)
    return {"property_id": prop.id, "start": first.isoformat(), "days": days,
            "taken": book.taken_nights(db, tenant.id, prop, first, first + timedelta(days=days))}


@router.post("/sites/{host}/quote")
def quote(host: str, body: QuoteIn, db: Session = Depends(get_db)):
    tenant, site, _ = _live(db, host)
    try:
        prop = book.property_for(db, site, body.property_id)
        q = book.make_quote(db, tenant, site, prop, body)
    except WebsiteError as exc:
        _fail(exc)
    free = book.is_free(db, tenant.id, prop, body.check_in, body.check_out)
    out = q.to_api()
    if not site_settings(site).show_prices:
        out = {k: v for k, v in out.items() if k in ("property_id", "check_in", "check_out", "adults", "children", "nights_count")}
    return {"available": free, "quote": out, "mode": site_settings(site).booking_mode}


@router.post("/sites/{host}/holds", status_code=201)
def hold(host: str, body: HoldIn, request: Request, db: Session = Depends(get_db)):
    tenant, site, _ = _live(db, host)
    try:
        # Refusals are raised before anything is written (a failed payment link leaves only a "failed" hold, which
        # holds nothing); the request session is discarded uncommitted.
        out = book.create_hold(db, tenant, site, pub.normalise_host(host), body, ip_hash=_ip_hash(request),
                               user_agent=request.headers.get("user-agent"))
    except WebsiteError as exc:
        if exc.code == "payment_link_failed":
            db.commit()
        _fail(exc)
    db.commit()
    return out


@router.get("/sites/{host}/holds/{hold_id}")
def hold_status(host: str, hold_id: str, s: str = Query(..., min_length=16, max_length=80), db: Session = Depends(get_db)):
    tenant, _site = _resolve(db, host)
    try:
        out = book.hold_status(db, tenant.id, hold_id, s)
    except WebsiteError as exc:
        _fail(exc)
    db.commit()
    return out


@router.post("/sites/{host}/enquiries", status_code=201)
def enquiries(host: str, body: EnquiryIn, request: Request, db: Session = Depends(get_db)):
    tenant, site, _ = _live(db, host)
    try:
        out = make_enquiry(db, tenant.id, site.id, pub.normalise_host(host), body, ip_hash=_ip_hash(request),
                           user_agent=request.headers.get("user-agent"))
    except ValueError:      # invalid phone: raised before anything is written
        raise HTTPException(status_code=422, detail={"code": "invalid_phone", "message": "Enter a mobile number we can reach."})
    db.commit()
    return {"status": out["status"]}


@router.post("/sites/{host}/manage/lookup")
def manage_lookup(host: str, body: ManageLookupIn, db: Session = Depends(get_db)):
    """Always the same answer, so a stranger learns nothing about whether a booking exists."""
    tenant, site, _ = _live(db, host)
    stay_row = book.find_stay_by_ref(db, tenant.id, body.ref, body.phone)
    if stay_row:
        try:
            from app.workers.tasks.website import send_manage_link
            send_manage_link.delay(tenant.id, stay_row.id, pub.normalise_host(host))
        except Exception:  # noqa: BLE001
            pass
    return {"status": "sent", "message": "If those details match a booking, we've sent a link to your email and WhatsApp."}


@router.get("/sites/{host}/manage")
def manage(host: str, t: str = Query(..., min_length=20, max_length=80), db: Session = Depends(get_db)):
    tenant, _site = _resolve(db, host)
    try:
        stay_row = book.stay_for_token(db, tenant.id, t)
    except WebsiteError as exc:
        _fail(exc)
    out = book.manage_view(db, tenant.id, stay_row)
    db.commit()
    return out


@router.post("/sites/{host}/manage/pay")
def manage_pay(host: str, t: str = Query(..., min_length=20, max_length=80), db: Session = Depends(get_db)):
    tenant, _site = _resolve(db, host)
    try:
        stay_row = book.stay_for_token(db, tenant.id, t)
    except WebsiteError as exc:
        _fail(exc)
    url = book.balance_link(db, tenant.id, stay_row)
    db.commit()
    if not url:
        raise HTTPException(status_code=409, detail={"code": "nothing_due", "message": "There's nothing to pay online right now."})
    return {"payment_url": url}


@router.get("/sites/{host}/media/{asset_id}")
def media(host: str, asset_id: str, db: Session = Depends(get_db)):
    tenant, site, v = _live(db, host)
    try:
        url = pub.media_url(db, tenant.id, v.doc, asset_id)
    except WebsiteError as exc:
        _fail(exc)
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "public, max-age=1800"})


@router.get("/preview/{token}/media/{asset_id}")
def preview_media(token: str, asset_id: str, db: Session = Depends(get_db)):
    try:
        tenant, _site, v = pub.read_preview(db, token)
        url = pub.media_url(db, tenant.id, v.doc, asset_id)
    except WebsiteError as exc:
        _fail(exc)
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "private, max-age=600"})


@router.get("/sites/{host}/links")
def links(host: str, db: Session = Depends(get_db)):
    """The link-in-bio page (agency M6): recent Instagram posts, each linking to the site tagged with that post's
    utm_campaign, so an enquiry or booking from it traces back to the post; and the published retail packages with an
    "Enquire on WhatsApp" link naming the package (bio_packages; prices only in grounded price mode). Public data only."""
    from app.services import bio_packages, marketing_links
    tenant, site, v = _live(db, host)
    home = f"https://{host}/"
    return {"name": (v.doc or {}).get("site", {}).get("name") or tenant.name,
            "book_url": marketing_links.tag_url(home, marketing_links.utm(source="instagram", medium="bio", campaign="bio")),
            "items": marketing_links.bio_items(db, tenant.id, home),
            "packages": bio_packages.items(db, tenant, v.doc)}


@router.post("/sites/{host}/views", status_code=204)
def views(host: str, body: PageViewIn, db: Session = Depends(get_db)):
    try:
        tenant, site = pub.resolve_host(db, host)
    except WebsiteError:
        return None
    pub.record_view(db, tenant.id, site.id, body.path, body.source, book.today_for(db, tenant.id))
    db.commit()
    return None
