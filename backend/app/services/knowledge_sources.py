"""Knowledge from what the team already publishes: Instagram posts and reels, and the text of running Meta ads.

The owner's problem (Oct 2026): the social media team opened a Dasara Mysore route and posted it on Instagram, but nobody typed it
into the knowledge base, so the bot did not know Mysore. This reads the tenant's OWN content through official APIs only:

* Instagram: the account's posts/reels (caption, type, permalink, timestamp) with the EXISTING Instagram connection token
  (integration kind "instagram"), graph.instagram.com only. No scraping, nothing of anybody else's.
* Meta ads: the creative title/body HAIP already stores in ``ad_entities`` (synced by meta_ads_service) -- no extra API call.

Each post or ad becomes ONE knowledge entry (source "instagram" / "meta_ad", ``source_ref`` = "ig:<media id>" / "ad:<ad id>",
``source_published_at`` = when it was posted / started). Re-running is idempotent: unchanged content is left alone, an edited caption
updates the entry (re-indexed before use), a post that disappeared or an ad that stopped running is marked out of date.

Review: per-tenant setting ``brand_config.knowledge.auto_approve_social`` (default False). Off: entries arrive "pending" and the owner
approves them on the knowledge page (nothing changes for guests until then). On: they are used as soon as indexed -- EXCEPT a post
that quotes a price, which always waits for the owner. Prices never come from social text anyway: figures are stripped from every
knowledge passage before the concierge sees it (price_policy.strip_prices); the live price comes only from published business data.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeEntry
from app.services import knowledge_service

log = structlog.get_logger()

SOCIAL_SOURCES = ("instagram", "meta_ad")
DEFAULT_SETTINGS = {"auto_approve_social": False, "social_sync": True, "website_recrawl": False, "social_max_age_days": 180}
MAX_POSTS = 50
_MAX_CONTENT = 7800
_OFFER_RE = re.compile(r"\b(offer|discount|deal|sale|early[- ]bird|coupon|promo|flat \d+|\d+\s?% ?off|limited period|save)\b", re.I)
_ROUTE_RE = re.compile(r"\b(route|routes|itinerary|trip|trail|via|road ?trip|destination|darshan|circuit)\b|→|->", re.I)


def settings(tenant) -> dict:
    """The tenant's knowledge-source settings, with defaults (brand_config.knowledge)."""
    raw = ((getattr(tenant, "brand_config", None) or {}).get("knowledge") or {})
    out = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        val = raw.get(key)
        if isinstance(default, bool) and isinstance(val, bool):
            out[key] = val
        elif isinstance(default, int) and not isinstance(default, bool) and isinstance(val, int) and 7 <= val <= 730:
            out[key] = val
    return out


def content_flags(text: str) -> list[str]:
    """Flags for the reviewer: a quoted price (never used as a price) and an offer/discount mention."""
    from app.services.price_policy import strip_prices
    flags = []
    if strip_prices(text or "") != (text or ""):
        flags.append("mentions_price")
    if _OFFER_RE.search(text or ""):
        flags.append("mentions_offer")
    return flags


def _category(text: str) -> str:
    return "routes" if _ROUTE_RE.search(text or "") else "other"


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None


@dataclass
class SyncReport:
    seen: int = 0
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    marked_out_of_date: int = 0
    skipped_old: int = 0

    def as_dict(self) -> dict:
        return {"seen": self.seen, "created": len(self.created), "updated": len(self.updated), "unchanged": self.unchanged,
                "marked_out_of_date": self.marked_out_of_date, "skipped_old": self.skipped_old}


def _upsert(db: Session, tenant_id: str, report: SyncReport, *, source: str, ref: str, content: str, url: Optional[str],
            published_at: Optional[datetime], auto_approve: bool) -> None:
    content = content.strip()[:_MAX_CONTENT]
    flags = content_flags(content)
    status = "approved" if (auto_approve and "mentions_price" not in flags) else "pending"
    entry = db.query(KnowledgeEntry).filter_by(tenant_id=tenant_id, source=source, source_ref=ref).first()
    if entry is None:
        entry = KnowledgeEntry(
            id=str(uuid.uuid4()), tenant_id=tenant_id, category=_category(content), question=None, content=content,
            source=source, source_url=url, source_ref=ref, priority=0, is_active=True, review_status=status,
            embedding_status="pending", source_published_at=published_at, content_flags=flags or None,
        )
        db.add(entry)
        report.created.append(entry.id)
        return
    if entry.stale_since is not None and entry.content == content:
        entry.stale_since = None                       # back again (a re-activated ad)
    if entry.content == content:
        report.unchanged += 1
        return
    entry.content = content
    entry.content_flags = flags or None
    entry.source_url = url or entry.source_url
    entry.source_published_at = published_at or entry.source_published_at
    entry.stale_since = None
    entry.embedding_status, entry.embedding_error, entry.embedding_attempts = "pending", None, 0
    entry.review_status = status                       # an edited caption is new text: reviewed again unless auto-approve
    report.updated.append(entry.id)


def _finish(db: Session, tenant_id: str, report: SyncReport, source: str) -> None:
    """One chained kb.* audit row for the run (like a crawl), commit, then queue indexing for what changed."""
    if report.created or report.updated or report.marked_out_of_date:
        knowledge_service.audit_change(db, tenant_id, None, "ingested", source, source=source, actor=f"{source}_sync",
                                       **report.as_dict(), entry_ids=(report.created + report.updated)[:100])
    db.commit()
    for entry_id in report.created + report.updated:
        try:
            from app.workers.tasks.embed_knowledge import embed_entry as embed_task
            embed_task.delay(tenant_id, entry_id)
        except Exception as exc:  # noqa: BLE001 -- the periodic sweep picks a pending entry up
            log.warning("kb_social_embed_enqueue_failed", tenant_id=tenant_id, entry_id=entry_id, error=str(exc))


def _instagram_integration(db: Session, tenant_id: str):
    from app.models.integration import Integration
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram", status="active").first()


def _save_state(integ, **state) -> None:
    cfg = dict(integ.config or {})
    cfg["kb_sync"] = {**(cfg.get("kb_sync") or {}), **state}
    integ.config = cfg


def sync_instagram(db: Session, tenant, *, adapter=None) -> dict:
    """Read the account's newest posts/reels into the knowledge base. Returns a summary; never raises for an API error."""
    import httpx
    from app.core.encryption import decrypt_credentials

    conf = settings(tenant)
    integ = _instagram_integration(db, tenant.id)
    if integ is None:
        return {"status": "not_connected"}
    now = datetime.now(timezone.utc)
    if adapter is None:
        creds = decrypt_credentials(integ.credentials_kms_blob) if integ.credentials_kms_blob else {}
        account_id = (integ.config or {}).get("instagram_business_account_id", "")
        if not creds.get("access_token") or not account_id:
            _save_state(integ, last_run_at=now.isoformat(), last_error="Instagram connection has no token or account id")
            db.commit()
            return {"status": "not_configured"}
        from app.adapters.instagram.meta_graph import InstagramGraphAdapter
        adapter = InstagramGraphAdapter(access_token=creds["access_token"], ig_account_id=account_id)

    items: list[dict] = []
    cursor = None
    try:
        while len(items) < MAX_POSTS:
            page, cursor = adapter.list_media_page(limit=25, after=cursor)
            items.extend(page)
            if not cursor or not page:
                break
    except httpx.HTTPStatusError as exc:
        # Status only: the response body can echo request details. A 400/403 here usually means the token lacks the
        # instagram_business_basic permission or the connection expired.
        _save_state(integ, last_run_at=now.isoformat(), last_error=f"Instagram API returned HTTP {exc.response.status_code}")
        db.commit()
        log.warning("kb_instagram_sync_api_error", tenant_id=tenant.id, status=exc.response.status_code)
        return {"status": "api_error", "http_status": exc.response.status_code}
    except httpx.HTTPError as exc:
        _save_state(integ, last_run_at=now.isoformat(), last_error="Instagram could not be reached")
        db.commit()
        log.warning("kb_instagram_sync_unreachable", tenant_id=tenant.id, error=type(exc).__name__)
        return {"status": "unreachable"}

    report = SyncReport()
    oldest_allowed = now - timedelta(days=conf["social_max_age_days"])
    fetched_refs, oldest_seen = set(), None
    for item in items[:MAX_POSTS]:
        media_id = str(item.get("id") or "").strip()
        caption = (item.get("caption") or "").strip()
        posted = _parse_ts(item.get("timestamp"))
        if not media_id:
            continue
        report.seen += 1
        fetched_refs.add(f"ig:{media_id}")
        if posted and (oldest_seen is None or posted < oldest_seen):
            oldest_seen = posted
        if not caption:
            continue                                   # a picture with no words teaches the bot nothing
        if posted and posted < oldest_allowed:
            report.skipped_old += 1
            continue
        kind = {"VIDEO": "reel", "REELS": "reel", "CAROUSEL_ALBUM": "post"}.get(str(item.get("media_type") or "").upper(), "post")
        label = f"Instagram {kind}" + (f" ({posted.date().isoformat()})" if posted else "")
        _upsert(db, tenant.id, report, source="instagram", ref=f"ig:{media_id}", content=f"{label}: {caption}",
                url=item.get("permalink"), published_at=posted, auto_approve=conf["auto_approve_social"])

    # A post we had, inside the window we just read, that is no longer there was deleted (or archived): stop using it.
    if oldest_seen is not None:
        for e in db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == tenant.id, KnowledgeEntry.source == "instagram",
                                                 KnowledgeEntry.stale_since.is_(None)).all():
            published = _parse_ts(e.source_published_at)
            if e.source_ref not in fetched_refs and published and published >= oldest_seen:
                e.stale_since = now
                report.marked_out_of_date += 1

    _save_state(integ, last_run_at=now.isoformat(), last_ok_at=now.isoformat(), last_error=None, **report.as_dict())
    _finish(db, tenant.id, report, "instagram")
    log.info("kb_instagram_synced", tenant_id=tenant.id, **report.as_dict())
    return {"status": "ok", **report.as_dict()}


def sync_meta_ads(db: Session, tenant) -> dict:
    """Running ads' creative text (title + body, never the internal ad name) into the knowledge base."""
    from app.models.ad_entity import AdEntity

    conf = settings(tenant)
    report = SyncReport()
    now = datetime.now(timezone.utc)
    running: set[str] = set()
    for ad in db.query(AdEntity).filter(AdEntity.tenant_id == tenant.id, AdEntity.level == "ad").all():
        creative = ad.creative or {}
        words = "\n".join(str(creative.get(k) or "").strip() for k in ("title", "body") if str(creative.get(k) or "").strip())
        if not words or (ad.effective_status or ad.status or "").upper() != "ACTIVE":
            continue
        report.seen += 1
        ref = f"ad:{ad.entity_id}"
        running.add(ref)
        started = _parse_ts(ad.starts_at)
        label = "Instagram/Facebook ad" + (f" (running since {started.date().isoformat()})" if started else "")
        _upsert(db, tenant.id, report, source="meta_ad", ref=ref, content=f"{label}: {words}", url=None, published_at=started,
                auto_approve=conf["auto_approve_social"])
    for e in db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == tenant.id, KnowledgeEntry.source == "meta_ad",
                                             KnowledgeEntry.stale_since.is_(None)).all():
        if e.source_ref not in running:
            e.stale_since = now                        # the ad stopped: what it promised may no longer hold
            report.marked_out_of_date += 1
    _finish(db, tenant.id, report, "meta_ad")
    return {"status": "ok", **report.as_dict()}
