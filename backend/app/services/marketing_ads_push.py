"""Putting an approved ad draft on Meta, pausing it, and the hourly watchdog (agency M5).

Push = claim (guarded UPDATE approved -> pushing) -> re-check content approval + money rules -> upload the approved
creative (the rendered post image, or the rendered reel) -> campaign (spend_cap) -> ad set (daily budget, dates,
audience) -> creative -> ad, every object PAUSED and its id committed at once -> switch ad, ad set, campaign ACTIVE.
A retry resumes from the saved ids, so a second campaign is never created. A Meta rate limit or outage puts the draft
back to `approved` for the Celery retry; anything else fails it, visibly. Celery `marketing_ads.push` (queue whatsapp).
"""
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.marketing.meta_ads import MetaAdsError
from app.core.audit import append_audit
from app.models.integration import Integration
from app.models.marketing_ads import MarketingAdDraft
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import marketing_ads_service as ads
from app.services import marketing_agency_service as agency
from app.services import marketing_content_service as content_svc
from app.services import meta_ads_service
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

MIN_RUN = timedelta(hours=24)        # Meta wants at least a day for a daily budget
START_DELAY = timedelta(minutes=10)


class TransientPushError(Exception):
    """Meta is rate limiting or down; the task retries."""


def _writer(db: Session, tenant_id: str):
    from app.adapters.marketing.meta_ads_write import MetaAdsWriter
    row = meta_ads_service.get_row(db, tenant_id)
    acct = ((row.config if row else None) or {}).get("ad_account_id")
    token, _ = meta_ads_service.get_token(db, tenant_id)
    if not acct or not token:
        raise MarketingError(409, "ads_not_connected", "Choose the Meta ad account on the Marketing page first.")
    return MetaAdsWriter(token, acct)


def page_and_instagram(db: Session, tenant_id: str) -> tuple[Optional[str], Optional[str]]:
    fb = db.query(Integration).filter_by(tenant_id=tenant_id, kind="facebook_page", status="active").first()
    ig = db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram", status="active").first()
    return ((fb.config or {}).get("page_id") if fb else None,
            (ig.config or {}).get("instagram_business_account_id") if ig else None)


def _media_url(asset: MediaAsset) -> str:
    from app.services.media_storage import get_presigned_media_url
    return get_presigned_media_url(asset.storage_key, expires_in=6 * 3600)


def _save(db: Session, draft: MarketingAdDraft, **ids) -> None:
    draft.meta = {**(draft.meta or {}), **ids}
    flag_modified(draft, "meta")
    db.commit()


def schedule_window(draft: MarketingAdDraft, now: datetime, latest_end: Optional[datetime]) -> tuple[datetime, datetime]:
    starts = now + START_DELAY
    ends = starts + timedelta(days=draft.days)
    if latest_end is not None:
        ends = min(ends, latest_end)
    return starts, max(ends, starts + MIN_RUN)


def push(db: Session, tenant_id: str, draft_id: str, *, writer_factory: Optional[Callable] = None,
         media_url: Optional[Callable[[MediaAsset], str]] = None, read_bytes: Optional[Callable[[str], bytes]] = None,
         latest_end: Optional[datetime] = None, now: Optional[datetime] = None) -> MarketingAdDraft:
    draft = ads.get_draft(db, tenant_id, draft_id)
    claimed = (db.query(MarketingAdDraft).filter(MarketingAdDraft.id == draft.id, MarketingAdDraft.status == "approved")
               .update({"status": "pushing", "tries": MarketingAdDraft.tries + 1}, synchronize_session=False))
    db.commit()
    if claimed != 1:
        return draft                              # another worker has it, or it was cancelled / already live
    db.refresh(draft)
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()

    def fail(message: str) -> MarketingAdDraft:
        draft.status, draft.error = "failed", message[:2000]
        append_audit(db, tenant_id=tenant_id, action="marketing.ad.failed", actor_user_id=None,
                     target_type="marketing_ad_draft", target_id=draft.id, payload={"actor": "agency", "error": message[:300]})
        db.commit()
        agency.notify_needs_approval(db, tenant_id, "Marketing: an ad could not start", message[:140])
        return draft

    # Re-check everything at the last moment: the post, the money, the kill switch.
    try:
        item = content_svc.get_item(db, tenant_id, draft.content_id)
        _, sha, payload = ads.ad_payload(db, tenant_id, item)
    except MarketingError as exc:
        return fail(exc.message)
    if sha != draft.content_sha:
        return fail("The post was approved again with new content after this ad was approved.")
    problems = ads.money_problems(db, tenant, draft)
    if problems:
        return fail(problems[0])
    page_id, ig_id = page_and_instagram(db, tenant_id)
    if not page_id:
        return fail("Connect the Facebook Page in Channels first; Meta ads run from a Page.")

    writer = (writer_factory or _writer)(db, tenant_id)
    url_for = media_url or _media_url
    m = dict(draft.meta or {})
    name = f"HAIP · {item.title}"[:180]
    try:
        if not m.get("currency_checked"):
            if writer.account_currency() != "INR":
                return fail("The Meta ad account is not in rupees; HAIP only runs ads in INR.")
            _save(db, draft, currency_checked=True)
        if not (m.get("image_hash") or m.get("video_id")):
            if item.kind == "reel":
                from app.services import marketing_reel
                video, cover = marketing_reel.render_reel(db, tenant, payload, read_bytes=read_bytes)
                db.commit()
                _save(db, draft, video_id=writer.upload_video(url_for(video)), thumbnail_url=url_for(cover))
            else:
                from app.services import marketing_render
                drawn = marketing_render.images(db, tenant, item.kind, payload, limit=1, read_bytes=read_bytes)
                _save(db, draft, image_hash=writer.upload_image(drawn[0][0]))
            m = dict(draft.meta or {})
        if latest_end is None:
            from app.services.marketing_boost import latest_end_for
            latest_end = latest_end_for(draft.window_key)          # a boost stops by noon on the weekend it sells
        starts, ends = schedule_window(draft, now or datetime.now(timezone.utc), latest_end)
        if not m.get("campaign_id"):
            _save(db, draft, campaign_id=writer.create_campaign(name, spend_cap_inr=draft.spend_cap_inr))
            m = dict(draft.meta)
        if not m.get("adset_id"):
            _save(db, draft, adset_id=writer.create_adset(name, campaign_id=m["campaign_id"], destination=draft.destination,
                                                           page_id=page_id, daily_budget_inr=draft.daily_budget_inr,
                                                           starts=starts, ends=ends, audience=draft.audience))
            m = dict(draft.meta)
        if not m.get("creative_id"):
            message = (payload.get("caption") or item.title)[:2000]
            _save(db, draft, creative_id=writer.create_creative(
                name, destination=draft.destination, page_id=page_id, instagram_user_id=ig_id, message=message,
                image_hash=m.get("image_hash"), video_id=m.get("video_id"), thumbnail_url=m.get("thumbnail_url")))
            m = dict(draft.meta)
        if not m.get("ad_id"):
            _save(db, draft, ad_id=writer.create_ad(name, adset_id=m["adset_id"], creative_id=m["creative_id"]))
            m = dict(draft.meta)
        for key in ("ad_id", "adset_id", "campaign_id"):          # inside out: nothing runs half-built
            writer.set_status(m[key], "ACTIVE")
    except MetaAdsError as exc:
        if exc.rate_limited or exc.status >= 500 or exc.status == 503:
            draft.status, draft.error = "approved", f"Meta is busy; will try again: {exc}"[:2000]
            db.commit()
            raise TransientPushError(str(exc)) from exc
        if exc.bad_token:
            return fail(f"Meta refused the token (it needs ads_management on the ad account): {exc}")
        return fail(f"Meta refused the ad: {exc}")
    except MarketingError as exc:
        return fail(exc.message)
    except Exception as exc:  # noqa: BLE001  storage or render trouble
        log.warning("marketing_ad_push_failed", tenant_id=tenant_id, draft_id=draft.id, error=str(exc)[:200])
        draft.status, draft.error = "approved", "The creative could not be prepared; will try again."
        db.commit()
        raise TransientPushError(str(exc)) from exc
    finally:
        writer.close()
    draft.status, draft.error, draft.starts_at, draft.ends_at = "live", None, starts, ends
    append_audit(db, tenant_id=tenant_id, action="marketing.ad.live", actor_user_id=None,
                 target_type="marketing_ad_draft", target_id=draft.id,
                 payload={"actor": "agency", "meta": m, "spend_cap_inr": draft.spend_cap_inr,
                          "starts_at": starts.isoformat(), "ends_at": ends.isoformat()})
    db.commit()
    return draft


def pause(db: Session, tenant_id: str, draft_id: str, actor_id: Optional[str], *, reason: str = "paused by a person",
          writer_factory: Optional[Callable] = None) -> MarketingAdDraft:
    draft = ads.get_draft(db, tenant_id, draft_id)
    if draft.status != "live":
        raise MarketingError(409, "wrong_state", "Only a running ad can be paused.")
    campaign = (draft.meta or {}).get("campaign_id")
    writer = (writer_factory or _writer)(db, tenant_id)
    try:
        writer.set_status(campaign, "PAUSED")
    except MetaAdsError as exc:
        raise MarketingError(502, "meta_error", f"Meta did not pause the ad: {exc}")
    finally:
        writer.close()
    draft.status = "paused"
    append_audit(db, tenant_id=tenant_id, action="marketing.ad.paused", actor_user_id=actor_id,
                 target_type="marketing_ad_draft", target_id=draft.id,
                 payload={"reason": reason, **({"actor": "agency"} if actor_id is None else {})})
    db.commit()
    return draft


def watch(db: Session, tenant: Tenant, *, now: Optional[datetime] = None,
          writer_factory: Optional[Callable] = None) -> dict:
    """Hourly: record spend from the Meta sync; pause an ad at its cap (Meta's spend_cap also stops it) and when the
    agency is paused; mark ads whose dates are over as ended."""
    now = now or datetime.now(timezone.utc)
    live = db.query(MarketingAdDraft).filter_by(tenant_id=tenant.id, status="live").all()
    spent = ads.spent_by_ad(db, tenant.id, [(d.meta or {}).get("ad_id") for d in live if (d.meta or {}).get("ad_id")])
    out = {"checked": len(live), "paused": 0, "ended": 0}
    killed = agency.get_agency(tenant)["paused"]
    for d in live:
        d.spent_inr = spent.get((d.meta or {}).get("ad_id"), d.spent_inr)
        ends = d.ends_at if d.ends_at is None or d.ends_at.tzinfo else d.ends_at.replace(tzinfo=timezone.utc)
        if ends is not None and ends <= now:
            d.status = "ended"
            out["ended"] += 1
            continue
        over = d.spent_inr is not None and d.spent_inr >= d.spend_cap_inr
        if over or killed:
            try:
                pause(db, tenant.id, d.id, None, reason="reached its cap" if over else "agency paused",
                      writer_factory=writer_factory)
                out["paused"] += 1
            except MarketingError as exc:
                log.warning("marketing_ad_watch_pause_failed", tenant_id=tenant.id, draft_id=d.id, error=exc.message)
    db.commit()
    return out
