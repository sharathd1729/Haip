"""What the bot knows, and how fresh it is -- one report per workspace for the owner, plus the actions that refresh it.

The owner's complaint (Oct 2026): "I update pricing, routes, itineraries and content, and the bot still replies with old data."
Every reason found is visible here, per source, so "why doesn't the bot know X" has an answer on one screen:

* knowledge entries by source (owner-typed, website, document, Instagram, ad, imported notes): how many the bot can use, how many
  wait for approval (never used until approved), are being indexed (an edited entry is NOT used until re-indexed), failed to index
  (and whether the automatic retry gave up -- it stops after ``MAX_AUTO_ATTEMPTS``), or are out of date (the page/post no longer
  says it);
* structured business data: published versions (the ONLY ones the bot reads), drafts waiting to be published, versions scheduled for
  a later date;
* property records (descriptions/FAQs shown to the bot beside the knowledge base) and the legacy rate tables;
* the Instagram sync and the website re-crawl, and the price setting (in "handoff" mode the bot never states a price).

``refresh`` is the owner's "Re-index now": re-queues everything not indexed or indexed from older wording, and fetches Instagram.
``recrawl_website`` re-reads the pages the workspace already imported (weekly, opt-in), through the existing SSRF-guarded fetcher.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeEntry
from app.services import knowledge_service, knowledge_sources

log = structlog.get_logger()

SOURCE_LABELS = {
    "manual": "Typed by your team", "website": "Website", "upload": "Documents", "document": "Documents",
    "conversation": "From conversations", "instagram": "Instagram posts", "meta_ad": "Ads", "owner_notes": "Imported notes",
}
MAX_RECRAWL_PAGES = 25


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _source_rows(db: Session, tenant_id: str) -> list[dict]:
    rows: dict[str, dict] = {}
    for e in db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == tenant_id).all():
        r = rows.setdefault(e.source, {
            "source": e.source, "label": SOURCE_LABELS.get(e.source, e.source.replace("_", " ").title()), "total": 0, "used_by_bot": 0,
            "waiting_approval": 0, "indexing": 0, "failed": 0, "gave_up": 0, "out_of_date": 0, "inactive": 0, "rejected": 0,
            "flagged_price": 0, "last_updated": None, "last_indexed": None,
        })
        r["total"] += 1
        if not e.is_active:
            r["inactive"] += 1
            continue
        if e.review_status == "rejected":
            r["rejected"] += 1
            continue
        if e.review_status == "pending":
            r["waiting_approval"] += 1
        if e.stale_since is not None:
            r["out_of_date"] += 1
        if e.embedding_status == "pending":
            r["indexing"] += 1
        elif e.embedding_status == "failed":
            r["failed"] += 1
            if int(e.embedding_attempts or 0) >= knowledge_service.MAX_AUTO_ATTEMPTS:
                r["gave_up"] += 1
        if "mentions_price" in (e.content_flags or []):
            r["flagged_price"] += 1
        if e.review_status == "approved" and e.embedding_status == "done" and e.stale_since is None:
            r["used_by_bot"] += 1                      # the exact retrieval rule (knowledge_service._ELIGIBLE_SQL)
        for key, val in (("last_updated", e.updated_at), ("last_indexed", e.embedded_at)):
            if val is not None and (r[key] is None or _iso(val) > r[key]):
                r[key] = _iso(val)
    return sorted(rows.values(), key=lambda r: (-r["total"], r["source"]))


def _business_data(db: Session, tenant_id: str) -> dict:
    from app.models.business_record import BusinessRecord
    from app.services.business_data_service import tenant_today

    today = tenant_today(db, tenant_id)
    out = {"published": 0, "drafts": 0, "scheduled": 0, "last_published_at": None, "by_kind": {}}
    for r in db.query(BusinessRecord).filter(BusinessRecord.tenant_id == tenant_id,
                                             BusinessRecord.status.in_(("published", "draft"))).all():
        kind = out["by_kind"].setdefault(r.kind, {"published": 0, "drafts": 0, "scheduled": 0})
        if r.status == "draft":
            out["drafts"] += 1
            kind["drafts"] += 1
            continue
        if r.effective_from and r.effective_from > today:
            out["scheduled"] += 1
            kind["scheduled"] += 1
        elif r.effective_to is None or r.effective_to >= today:
            out["published"] += 1
            kind["published"] += 1
        if r.published_at is not None and (out["last_published_at"] is None or _iso(r.published_at) > out["last_published_at"]):
            out["last_published_at"] = _iso(r.published_at)
    return out


def _records(db: Session, tenant_id: str) -> dict:
    from app.models.property import Property, RatePlan, SeasonalRate

    def last(model, *conds):
        return _iso(db.query(func.max(model.updated_at)).filter(model.tenant_id == tenant_id, *conds).scalar())
    return {
        "properties": db.query(func.count(Property.id)).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True)).scalar() or 0,
        "properties_last_updated": last(Property),
        "rate_tables_last_updated": max([v for v in (last(RatePlan), last(SeasonalRate)) if v] or [None]),
    }


def _instagram(db: Session, tenant, conf: dict) -> dict:
    integ = knowledge_sources._instagram_integration(db, tenant.id)
    state = ((integ.config or {}).get("kb_sync") or {}) if integ else {}
    return {"connected": integ is not None, "sync_enabled": conf["social_sync"], "last_run_at": state.get("last_run_at"),
            "last_ok_at": state.get("last_ok_at"), "last_error": state.get("last_error")}


def _website(db: Session, tenant_id: str, conf: dict) -> dict:
    q = db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == tenant_id, KnowledgeEntry.source == "website",
                                        KnowledgeEntry.source_url.isnot(None))
    pages = q.with_entities(func.count(func.distinct(KnowledgeEntry.source_url))).scalar() or 0
    return {"pages": pages, "recrawl_enabled": conf["website_recrawl"],
            "last_read_at": _iso(q.with_entities(func.max(KnowledgeEntry.updated_at)).scalar())}


def report(db: Session, tenant) -> dict:
    from app.services import price_policy

    conf = knowledge_sources.settings(tenant)
    sources = _source_rows(db, tenant.id)
    business = _business_data(db, tenant.id)
    instagram = _instagram(db, tenant, conf)
    website = _website(db, tenant.id, conf)
    price_mode = price_policy.price_mode(tenant)
    warnings: list[dict] = []

    def warn(code: str, text: str, level: str = "warning"):
        warnings.append({"code": code, "level": level, "text": text})

    total = lambda key: sum(r[key] for r in sources)  # noqa: E731
    if business["drafts"]:
        warn("unpublished_drafts", f"{business['drafts']} business-data draft(s) are not published. The bot reads only published versions.")
    if business["scheduled"]:
        warn("scheduled_versions", f"{business['scheduled']} published version(s) start on a later date; the bot uses the current one until then.", "info")
    if total("waiting_approval"):
        warn("waiting_approval", f"{total('waiting_approval')} knowledge item(s) wait for your approval. The bot does not use them until you approve.")
    if total("indexing"):
        warn("indexing", f"{total('indexing')} item(s) are being indexed. An edited item is not used until its new wording is indexed.", "info")
    if total("failed"):
        gave_up = total("gave_up")
        warn("failed", f"{total('failed')} item(s) failed to index" + (f" ({gave_up} stopped retrying on their own)" if gave_up else "")
             + ". Use Re-index now.")
    if total("out_of_date"):
        warn("out_of_date", f"{total('out_of_date')} item(s) are out of date (the page, post or ad no longer says it) and are not used.", "info")
    if instagram["connected"] and instagram["last_error"]:
        warn("instagram_error", f"Instagram could not be read: {instagram['last_error']}.")
    if not instagram["connected"]:
        warn("instagram_not_connected", "Instagram is not connected, so posts are not read into the knowledge base.", "info")
    if price_mode == "handoff":
        warn("price_handoff", "Price setting is 'hand off': the bot never states a price in chat; the team gives it.", "info")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "settings": conf, "price_mode": price_mode,
        "sources": sources, "business_data": business, "records": _records(db, tenant.id), "instagram": instagram,
        "website": website, "index": knowledge_service.index_health(db, tenant.id), "warnings": warnings,
    }


def refresh(db: Session, tenant, actor_id: Optional[str]) -> dict:
    """Re-index everything not indexed (or indexed from older wording) and fetch Instagram now. Audited; work runs in Celery."""
    conf = knowledge_sources.settings(tenant)
    queued = 0
    for e in db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == tenant.id, KnowledgeEntry.is_active.is_(True)).all():
        drifted = e.embedding_status == "done" and e.content_hash is not None and knowledge_service.needs_reembed(e)
        if e.embedding_status in ("pending", "failed") or drifted:
            e.embedding_status, e.embedding_error, e.embedding_attempts = "pending", None, 0
            queued += 1
    social = bool(conf["social_sync"] and knowledge_sources._instagram_integration(db, tenant.id) is not None)
    knowledge_service.audit_change(db, tenant.id, actor_id, "refresh_requested", "all", entries=queued, instagram_sync=social)
    db.commit()
    enqueue_refresh(tenant.id, reindex=bool(queued), social=social)
    return {"queued_for_indexing": queued, "instagram_sync_queued": social}


def enqueue_refresh(tenant_id: str, *, reindex: bool, social: bool) -> None:
    """The Celery side of refresh (a separate function so tests replace it: no broker in the test run)."""
    from app.workers.tasks import knowledge_sources_sync as tasks
    from app.workers.tasks.embed_knowledge import embed_pending
    if reindex:
        embed_pending.apply_async(kwargs={"tenant_id": tenant_id, "limit": 500, "force": True})
    if social:
        tasks.sync_tenant.apply_async(kwargs={"tenant_id": tenant_id})


def recrawl_website(db: Session, tenant_id: str) -> dict:
    """Re-read every page this workspace already imported. Unchanged passages stay; new ones arrive pending review; passages the
    page no longer has are marked out of date (knowledge_ingest.ingest_chunks_report). SSRF-guarded fetch (safe_get)."""
    from app.services import knowledge_ingest

    urls = [u for (u,) in db.query(KnowledgeEntry.source_url).filter(
        KnowledgeEntry.tenant_id == tenant_id, KnowledgeEntry.source == "website", KnowledgeEntry.source_url.isnot(None),
    ).distinct().limit(MAX_RECRAWL_PAGES).all()]
    out = {"pages": len(urls), "read": 0, "failed": 0, "new_passages": 0, "unchanged": 0, "marked_out_of_date": 0}
    for url in urls:
        try:
            text = knowledge_ingest.fetch_url_text(url)
        except knowledge_ingest.IngestError as exc:
            out["failed"] += 1
            log.warning("kb_recrawl_page_failed", tenant_id=tenant_id, error=str(exc)[:200])
            continue
        rep = knowledge_ingest.ingest_chunks_report(db, tenant_id, text, source="website", source_url=url)
        out["read"] += 1
        out["new_passages"] += len(rep.created)
        out["unchanged"] += rep.unchanged
        out["marked_out_of_date"] += rep.marked_out_of_date
    if urls:
        knowledge_service.audit_change(db, tenant_id, None, "ingested", urls[0], source="website", actor="website_recrawl", urls=urls, **out)
        db.commit()
    return out


def update_settings(db: Session, tenant, actor_id: Optional[str], changes: dict) -> dict:
    """Owner/manager change to brand_config.knowledge. Audited (kb.settings_updated) with the previous and new values."""
    from app.core.audit import append_audit

    before = knowledge_sources.settings(tenant)
    cfg = dict(tenant.brand_config or {})
    knowledge = dict(cfg.get("knowledge") or {})
    for key, val in changes.items():
        if key in knowledge_sources.DEFAULT_SETTINGS and val is not None:
            knowledge[key] = val
    cfg["knowledge"] = knowledge
    tenant.brand_config = cfg
    after = knowledge_sources.settings(tenant)
    diff = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
    if diff:
        append_audit(db, tenant_id=tenant.id, action="kb.settings_updated", actor_user_id=actor_id, target_type="tenant",
                     target_id=tenant.id, payload={"changes": diff})
    db.commit()
    return after
