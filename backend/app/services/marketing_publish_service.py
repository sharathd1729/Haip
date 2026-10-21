"""Scheduler + publisher (agency phase C).

  * Only an APPROVED version can be scheduled, and publishing sends only what `approved_payload()` returns (approved,
    still current, hashes match), so an edit after approval can never reach Instagram.
  * Publish role: `suggest` = a person with marketing.approve schedules; `autopilot` = an approved item is scheduled
    automatically at the suggested time. Approval itself is always a person. Kill switch: nothing is published.
  * One attempt row per (content, version), unique. Container and media ids are saved the moment they exist, and a
    retry first asks Instagram whether a stored container was already published, so a retry never posts twice.
  * What is posted is rendered from the approved payload (`marketing_render`): each photo cropped to the feed or story
    canvas with its slide / frame text drawn on, saved as a JPEG. A PNG or WebP library photo is therefore fine.
  * Transient failures (timeouts, 429/5xx, quota exhausted, media still processing) retry at +5, +15, +60 min; after
    MAX_TRIES the attempt fails and the item returns to "approved" with the reason shown.
"""
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Callable, Optional

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.encryption import decrypt_credentials
from app.core.tenant_tz import get_tz
from app.models.integration import Integration
from app.models.marketing import InstagramPostMetricDaily, MarketingContent, MarketingPublishAttempt
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import marketing_agency_service as agency
from app.services import marketing_content_service as content_svc
from app.services import marketing_render as render
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

MAX_TRIES = 3
BACKOFF_MIN = (5, 15, 60)
MAX_AHEAD_DAYS = 75
DEFAULT_HOUR = 10


# ── Preflight ───────────────────────────────────────────────────────────────────────────────────────────────────────

SOURCE_TYPES = ("image/jpeg", "image/png", "image/webp")


def _asset_ids(kind: str, payload: dict) -> list[Optional[str]]:
    return [f["asset_id"] for f in render.frames(kind, payload)]


def preflight(db: Session, tenant_id: str, item: MarketingContent, payload: dict) -> tuple[list[str], list[str]]:
    """(problems that block publishing, notes). Every slide or frame needs an approved library photo."""
    problems, notes = [], []
    ids = _asset_ids(item.kind, payload)
    if not ids or any(not a for a in ids):
        problems.append("Every slide or frame needs a photo from the library before it can be posted.")
    found = {a.id: a for a in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant_id,
                                                          MediaAsset.id.in_([a for a in ids if a]))} if any(ids) else {}
    for a in [x for x in ids if x]:
        asset = found.get(a)
        if asset is None or asset.status != "active":
            problems.append("A chosen photo is missing or not approved.")
        elif asset.mime_type not in SOURCE_TYPES:
            problems.append("Use a JPEG, PNG or WebP photo.")
    if item.kind == "story" and any(f.get("sticker") for f in payload.get("frames", [])):
        notes.append("Instagram's API cannot add poll, question or link stickers; add them in the app after posting.")
    return sorted(set(problems)), notes


# ── Scheduling ──────────────────────────────────────────────────────────────────────────────────────────────────────

def suggest_time(db: Session, tenant: Tenant, day: Optional[date] = None) -> datetime:
    """The local hour at which this account's posts reached most people (from post history), on `day`."""
    tz = get_tz(tenant)
    day = day or (datetime.now(tz).date() + timedelta(days=1))
    hours: dict[int, list[int]] = {}
    for posted_at, reach in (db.query(InstagramPostMetricDaily.posted_at, InstagramPostMetricDaily.reach)
                             .filter(InstagramPostMetricDaily.tenant_id == tenant.id,
                                     InstagramPostMetricDaily.reach.isnot(None)).limit(500)):
        try:
            h = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00").replace("+0000", "+00:00")).astimezone(tz).hour
        except (ValueError, TypeError):
            continue
        hours.setdefault(h, []).append(reach)
    best = max(hours, key=lambda h: median(hours[h])) if sum(len(v) for v in hours.values()) >= 5 else DEFAULT_HOUR
    when = datetime(day.year, day.month, day.day, best, 0, tzinfo=tz)
    now = datetime.now(timezone.utc)
    return when if when > now else now + timedelta(minutes=10)


def schedule(db: Session, tenant: Tenant, item_id: str, when: datetime, actor_id: str) -> MarketingPublishAttempt:
    if agency.level(tenant, "publish") == "off":
        raise MarketingError(409, "publishing_off", "Publishing is switched off for this workspace.")
    item = content_svc.get_item(db, tenant.id, item_id)
    if item.status != "approved":
        raise MarketingError(409, "not_approved", "Only approved content can be scheduled.")
    payload = content_svc.approved_payload(db, tenant.id, item.id)
    problems, _ = preflight(db, tenant.id, item, payload)
    if problems:
        raise MarketingError(422, "not_publishable", "This can't be posted yet.", problems)
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if when < now - timedelta(minutes=1) or when > now + timedelta(days=MAX_AHEAD_DAYS):
        raise MarketingError(422, "bad_time", f"Pick a time from now up to {MAX_AHEAD_DAYS} days ahead.")
    attempt = (db.query(MarketingPublishAttempt)
               .filter_by(tenant_id=tenant.id, content_id=item.id, version_id=item.approved_version_id).first())
    if attempt is not None and attempt.status in ("published", "publishing"):
        raise MarketingError(409, "already_published", "This version is already posted or being posted.")
    if attempt is None:
        attempt = MarketingPublishAttempt(tenant_id=tenant.id, content_id=item.id, version_id=item.approved_version_id,
                                          sha256=item.approved_sha256, scheduled_for=when, scheduled_by=actor_id)
        db.add(attempt)
    attempt.status, attempt.scheduled_for, attempt.error, attempt.tries = "scheduled", when, None, 0
    item.status = "scheduled"
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="marketing.content.scheduled", actor_user_id=actor_id,
                 target_type="marketing_content", target_id=item.id,
                 payload={"version_id": attempt.version_id, "scheduled_for": when.isoformat()})
    return attempt


def unschedule(db: Session, tenant_id: str, item_id: str, actor_id: str) -> None:
    item = content_svc.get_item(db, tenant_id, item_id)
    n = (db.query(MarketingPublishAttempt)
         .filter_by(tenant_id=tenant_id, content_id=item.id, status="scheduled")
         .update({"status": "cancelled"}, synchronize_session=False))
    if n == 0:
        raise MarketingError(409, "not_scheduled", "Nothing is scheduled for this content.")
    item.status = "approved"
    append_audit(db, tenant_id=tenant_id, action="marketing.content.unscheduled", actor_user_id=actor_id,
                 target_type="marketing_content", target_id=item.id, payload={})


def on_approved(db: Session, tenant: Tenant, item_id: str) -> Optional[MarketingPublishAttempt]:
    """With the publish role on autopilot, an approved item is scheduled at the suggested time on its planned day."""
    if agency.level(tenant, "publish") != "autopilot":
        return None
    item = content_svc.get_item(db, tenant.id, item_id)
    try:
        day = date.fromisoformat(item.planned_for) if item.planned_for else None
        return schedule(db, tenant, item.id, suggest_time(db, tenant, day), "agency")
    except MarketingError as exc:
        log.info("auto_schedule_skipped", tenant_id=tenant.id, item_id=item.id, reason=exc.message)
        return None


def cancel_for_edit(db: Session, tenant_id: str, item_id: str) -> int:
    """An edit voids the approval; whatever was scheduled for the old version is cancelled with it."""
    return (db.query(MarketingPublishAttempt)
            .filter(MarketingPublishAttempt.tenant_id == tenant_id, MarketingPublishAttempt.content_id == item_id,
                    MarketingPublishAttempt.status == "scheduled")
            .update({"status": "cancelled", "error": "Content changed after approval"}, synchronize_session=False))


# ── Publishing ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _caption(payload: dict) -> str:
    tags = " ".join(payload.get("hashtags") or [])
    return (payload.get("caption") or "") + (f"\n\n{tags}" if tags else "")


def _publisher_for(db: Session, tenant_id: str):
    from app.adapters.instagram.publishing import Publisher
    integ = db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram", status="active").first()
    creds = decrypt_credentials(integ.credentials_kms_blob) if integ and integ.credentials_kms_blob else {}
    ig = (integ.config or {}).get("instagram_business_account_id") if integ else None
    if not creds.get("access_token") or not ig:
        raise MarketingError(409, "instagram_not_connected", "Instagram is not connected for this workspace.")
    return Publisher(creds["access_token"], ig)


def due(db: Session, now: Optional[datetime] = None) -> list[MarketingPublishAttempt]:
    now = now or datetime.now(timezone.utc)
    return (db.query(MarketingPublishAttempt)
            .filter(MarketingPublishAttempt.status == "scheduled", MarketingPublishAttempt.scheduled_for <= now)
            .order_by(MarketingPublishAttempt.scheduled_for.asc()).limit(50).all())


def publish_attempt(db: Session, attempt_id: str, *, publisher_factory: Optional[Callable] = None,
                    media_url: Optional[Callable[[MediaAsset], str]] = None,
                    read_bytes: Optional[Callable[[str], bytes]] = None) -> MarketingPublishAttempt:
    from app.adapters.instagram.publishing import PublishError
    from app.services.media_storage import get_presigned_media_url

    attempt = db.query(MarketingPublishAttempt).filter_by(id=attempt_id).one()
    claimed = (db.query(MarketingPublishAttempt)
               .filter(MarketingPublishAttempt.id == attempt.id, MarketingPublishAttempt.status == "scheduled")
               .update({"status": "publishing", "tries": MarketingPublishAttempt.tries + 1}, synchronize_session=False))
    db.commit()
    if claimed != 1:
        return attempt                      # another worker has it, or it was cancelled / already done
    db.refresh(attempt)
    tenant = db.query(Tenant).filter_by(id=attempt.tenant_id).one()
    item = content_svc.get_item(db, tenant.id, attempt.content_id)
    url_for = media_url or (lambda a: get_presigned_media_url(a.storage_key, expires_in=3600))

    def fail(msg: str, transient: bool) -> MarketingPublishAttempt:
        if transient and attempt.tries < MAX_TRIES:
            attempt.status = "scheduled"
            attempt.scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=BACKOFF_MIN[attempt.tries - 1])
        else:
            attempt.status = "failed"
            item.status = "approved"
            agency.notify_needs_approval(db, tenant.id, "Marketing: a post could not be published", item.title)
        attempt.error = msg[:2000]
        append_audit(db, tenant_id=tenant.id, action="marketing.content.publish_failed", actor_user_id="agency",
                     target_type="marketing_content", target_id=item.id, payload={"error": msg[:300], "will_retry": attempt.status == "scheduled"})
        db.commit()
        return attempt

    if agency.get_agency(tenant)["paused"] or agency.level(tenant, "publish") == "off":
        attempt.status, attempt.error = "scheduled", "Agency paused: not posted. Resume the agency to post."
        attempt.scheduled_for = datetime.now(timezone.utc) + timedelta(hours=1)
        attempt.tries -= 1
        db.commit()
        return attempt
    try:
        payload = content_svc.approved_payload(db, tenant.id, item.id)
        if item.approved_version_id != attempt.version_id or item.approved_sha256 != attempt.sha256:
            raise MarketingError(409, "approval_stale", "The content changed after it was scheduled.")
    except MarketingError as exc:
        attempt.status, attempt.error = "cancelled", exc.message
        db.commit()
        return attempt
    problems, notes = preflight(db, tenant.id, item, payload)
    if problems:
        return fail("; ".join(problems), False)

    from app.services.media_library_service import MediaError
    containers = list(attempt.container_ids or [])
    images: list[MediaAsset] = []
    if not containers:
        try:
            images = render.render(db, tenant, item.kind, payload, read_bytes=read_bytes)
            db.commit()
        except MediaError as exc:
            return fail(exc.message, False)
        except Exception as exc:                     # storage read/write failed: try again later
            db.rollback()
            log.warning("marketing_render_failed", tenant_id=tenant.id, item_id=item.id, error=str(exc)[:200])
            return fail("The images could not be prepared; will try again.", True)
    pub = (publisher_factory or _publisher_for)(db, tenant.id)
    try:
        left = pub.quota_left()
        if left == 0:
            return fail("Instagram's 24-hour posting limit is used up.", True)
        containers = list(attempt.container_ids or [])
        published = list(attempt.media_ids or [])
        if item.kind == "carousel":
            if not containers:
                kids = [pub.image_container(url_for(a), carousel_item=True) for a in images]
                for k in kids:
                    pub.wait_ready(k)
                containers = [pub.carousel_container(kids, _caption(payload))]
        elif item.kind == "story":
            if not containers:
                containers = [pub.image_container(url_for(a), story=True) for a in images]
        elif not containers:
            containers = [pub.image_container(url_for(images[0]), caption=_caption(payload))]
        attempt.container_ids = containers
        db.commit()                                   # saved before publishing: a retry reuses these containers
        for cid in containers[len(published):]:
            if pub.container_status(cid) == "PUBLISHED":
                raise PublishError("A previous try already posted this; check Instagram before posting again.", transient=False)
            pub.wait_ready(cid)
            published.append(pub.publish(cid))
            attempt.media_ids = list(published)
            db.commit()                               # saved immediately after each post
        if payload.get("first_comment") and published:
            try:
                pub.comment(published[0], payload["first_comment"])
            except PublishError as exc:
                notes.append(f"First comment not posted: {exc}")
        attempt.permalink = pub.permalink(published[0]) if published else None
    except PublishError as exc:
        return fail(str(exc), exc.transient)
    finally:
        pub.close()
    attempt.status, attempt.published_at, attempt.error = "published", datetime.now(timezone.utc), ("; ".join(notes) or None)
    item.status = "published"
    from app.services import usage_service
    usage_service.record(db, tenant.id, module="marketing_studio", kind="publish", units=len(published),
                         provider="instagram", ref_type="marketing_content", ref_id=item.id)
    append_audit(db, tenant_id=tenant.id, action="marketing.content.published", actor_user_id="agency",
                 target_type="marketing_content", target_id=item.id,
                 payload={"version_id": attempt.version_id, "media_ids": published, "permalink": attempt.permalink})
    db.commit()
    return attempt
