"""iCal calendar links: connect a property to Airbnb / Booking.com / Google
Calendar (or any calendar that speaks iCal) by pasting a link.

  GET    /ical-feeds                      list links with status and export URL
  POST   /ical-feeds                      add a link (import URL optional)
  PATCH  /ical-feeds/{id}                 rename, change the import URL, pause
  DELETE /ical-feeds/{id}                 remove; lifts the blocks it imported
  POST   /ical-feeds/{id}/sync            read the other calendar now
  POST   /ical-feeds/{id}/regenerate      new export URL (the old one stops working)

  GET    /ical/{token}.ics                HAIP's calendar for the property (public)

The export URL is public by design -- the other side has to fetch it without
logging in -- and protected the way OTA calendar links are: an unguessable
token. Anyone holding it can read availability (dates only, never guest
details), so regenerating it is one click.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.core.config import settings
from app.core.database import get_db, set_tenant_context
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.core.url_safety import UnsafeURLError, assert_public_url
from app.models.ical_feed import ICalFeed
from app.models.property import BlockedDate, Property
from app.models.user import User, UserRole
from app.services import ical_sync_service as svc

router = APIRouter(prefix="/ical-feeds", tags=["ical"])
public_router = APIRouter(prefix="/ical", tags=["ical"])

_MANAGE = (UserRole.OWNER, UserRole.MANAGER)


class FeedCreate(BaseModel):
    property_id: str
    name: str = Field(min_length=1, max_length=80)
    import_url: Optional[str] = Field(default=None, max_length=2000)


class FeedUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    import_url: Optional[str] = Field(default=None, max_length=2000)   # "" removes the import side
    is_active: Optional[bool] = None


def _clean_url(raw: str) -> str:
    url = raw.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    try:
        assert_public_url(url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return url


def _export_url(feed: ICalFeed) -> str:
    return f"{settings.API_BASE_URL.rstrip('/')}/api/v1/ical/{feed.export_token}.ics"


def _import_hint(feed: ICalFeed) -> Optional[str]:
    """Where the saved link points, without revealing the secret part."""
    if not feed.import_url_enc:
        return None
    url = decrypt_credentials(feed.import_url_enc).get("url", "")
    try:
        from urllib.parse import urlsplit
        return (urlsplit(url).hostname or "") + "/…"
    except Exception:  # noqa: BLE001
        return "saved"


def _out(feed: ICalFeed, prop_name: Optional[str]) -> dict:
    return {
        "id": feed.id, "property_id": feed.property_id, "property_name": prop_name, "name": feed.name,
        "has_import": bool(feed.import_url_enc), "import_hint": _import_hint(feed),
        "export_url": _export_url(feed), "is_active": feed.is_active,
        "last_synced_at": feed.last_synced_at.isoformat() if feed.last_synced_at else None,
        "last_status": feed.last_status, "last_error": feed.last_error,
        "last_event_count": feed.last_event_count, "last_conflicts": feed.last_conflicts or 0,
    }


def _get_feed(db: Session, user: User, feed_id: str) -> ICalFeed:
    feed = db.query(ICalFeed).filter_by(id=feed_id, tenant_id=user.tenant_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Calendar link not found")
    return feed


@router.get("")
def list_feeds(current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    names = {p.id: p.name for p in db.query(Property).filter_by(tenant_id=current_user.tenant_id).all()}
    feeds = db.query(ICalFeed).filter_by(tenant_id=current_user.tenant_id).order_by(ICalFeed.created_at).all()
    return [_out(f, names.get(f.property_id)) for f in feeds]


@router.post("", status_code=201)
def create_feed(body: FeedCreate, current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    prop = db.query(Property).filter_by(id=body.property_id, tenant_id=current_user.tenant_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if db.query(ICalFeed).filter_by(tenant_id=current_user.tenant_id, property_id=prop.id).count() >= svc.feed_cap():
        raise HTTPException(status_code=422, detail=f"A property can have at most {svc.feed_cap()} calendar links.")
    feed = ICalFeed(tenant_id=current_user.tenant_id, property_id=prop.id, name=body.name.strip(),
                    export_token=svc.new_export_token(), is_active=True)
    if body.import_url and body.import_url.strip():
        feed.import_url_enc = encrypt_credentials({"url": _clean_url(body.import_url)})
    db.add(feed)
    db.flush()
    append_audit(db, tenant_id=current_user.tenant_id, action="ical.feed_created", actor_user_id=current_user.id,
                 target_type="ical_feed", target_id=feed.id, payload={"property_id": prop.id, "name": feed.name,
                                                                      "has_import": bool(feed.import_url_enc)})
    db.commit()
    set_tenant_context(db, current_user.tenant_id)
    result = svc.sync_feed(db, feed) if feed.import_url_enc else None     # fail early on a wrong link
    set_tenant_context(db, current_user.tenant_id)
    db.refresh(feed)
    return {**_out(feed, prop.name), "sync": result}


@router.patch("/{feed_id}")
def update_feed(feed_id: str, body: FeedUpdate, current_user: User = Depends(require_roles(*_MANAGE)),
                db: Session = Depends(get_db)):
    feed = _get_feed(db, current_user, feed_id)
    if body.name is not None:
        feed.name = body.name.strip()
    if body.import_url is not None:
        feed.import_url_enc = encrypt_credentials({"url": _clean_url(body.import_url)}) if body.import_url.strip() else None
    if body.is_active is not None:
        feed.is_active = body.is_active
    db.commit()
    set_tenant_context(db, feed.tenant_id)
    prop = db.query(Property).filter_by(id=feed.property_id, tenant_id=feed.tenant_id).first()
    return _out(feed, prop.name if prop else None)


@router.delete("/{feed_id}", status_code=204)
def delete_feed(feed_id: str, current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    feed = _get_feed(db, current_user, feed_id)
    # Lift what this link imported: its source is gone, so nothing would ever
    # free those dates again. Blocks a person made by hand are untouched.
    for b in db.query(BlockedDate).filter(BlockedDate.tenant_id == feed.tenant_id,
                                          BlockedDate.notes.like(svc.marker(feed.id) + "%")).all():
        b.is_active = False
    append_audit(db, tenant_id=current_user.tenant_id, action="ical.feed_deleted", actor_user_id=current_user.id,
                 target_type="ical_feed", target_id=feed.id, payload={"property_id": feed.property_id, "name": feed.name})
    db.delete(feed)
    db.commit()


@router.post("/{feed_id}/sync")
def sync_now(feed_id: str, current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    feed = _get_feed(db, current_user, feed_id)
    if not feed.import_url_enc:
        raise HTTPException(status_code=422, detail="This link has no import URL, so there is nothing to read.")
    result = svc.sync_feed(db, feed)
    set_tenant_context(db, feed.tenant_id)
    prop = db.query(Property).filter_by(id=feed.property_id, tenant_id=feed.tenant_id).first()
    return {**_out(feed, prop.name if prop else None), "sync": result}


@router.post("/{feed_id}/regenerate")
def regenerate(feed_id: str, current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    feed = _get_feed(db, current_user, feed_id)
    feed.export_token = svc.new_export_token()
    append_audit(db, tenant_id=current_user.tenant_id, action="ical.export_url_regenerated",
                 actor_user_id=current_user.id, target_type="ical_feed", target_id=feed.id, payload={})
    db.commit()
    set_tenant_context(db, feed.tenant_id)
    prop = db.query(Property).filter_by(id=feed.property_id, tenant_id=feed.tenant_id).first()
    return _out(feed, prop.name if prop else None)


# ─── Public export ────────────────────────────────────────────────────────────

@public_router.get("/{filename}")
def export_calendar(filename: str, db: Session = Depends(get_db)):
    """HAIP's calendar for one link. Unknown, paused and removed links all answer
    404, so the URL space can't be probed."""
    token = filename[:-4] if filename.endswith(".ics") else filename
    tenant_id = svc.tenant_for_export_token(db, token) if 20 <= len(token) <= 64 else None
    feed = None
    if tenant_id:
        set_tenant_context(db, tenant_id)
        feed = db.query(ICalFeed).filter_by(export_token=token, tenant_id=tenant_id).first()
    if not feed or not feed.is_active:
        raise HTTPException(status_code=404, detail="Not found")
    prop = db.query(Property).filter_by(id=feed.property_id, tenant_id=feed.tenant_id).first()
    body = svc.build_ics(f"{prop.name if prop else 'Property'} (HAIP)", svc.export_events(db, feed))
    return Response(content=body, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=300", "Content-Disposition": 'inline; filename="haip.ics"'})
