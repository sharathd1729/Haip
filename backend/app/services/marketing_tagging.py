"""AI tags for every post, Reel and ad (studio plan phase 1): format, length, hook, opening shot, angle, persona, emotion,
destination, talent, text on screen, CTA, pacing, audio, occasion (schemas/marketing_tags.py).

  * Subjects: the account's Instagram media seen by the insights poller (ALL posts, not only HAIP's) and the Meta ads
    with metrics, in the last LOOKBACK_DAYS. One record each (marketing_creative_tags, unique per subject).
  * What the AI reads is text HAIP already has: the caption, and for HAIP-made content the approved slide / frame text and
    the library photo descriptions; for ads the ad copy. No image is sent. Format (and "not a video") comes from the
    platform's own media type in code, never from the AI.
  * Router task `marketing_tagging` (Gemini 3.1 Flash-Lite, the low model), prompt marketing-tagging-v1, Celery only
    (`marketing_studio.tag_creative`); `queue_untagged` makes the pending rows (daily beat + before each report).
  * An owner correction (`correct`) is final: source=owner, audited, never re-tagged.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.prompt_versions import get_version
from app.models.ad_entity import AdEntity
from app.models.ad_metrics import AdMetric
from app.models.marketing import MarketingCreativeTag, MarketingPublishAttempt
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.schemas.marketing_tags import CreativeTags, CreativeTagsPatch, normalise
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as content_svc
from app.services import usage_service
from app.services.marketing_content_service import MarketingError
from app.services.marketing_prompts import _schema

log = structlog.get_logger()

LOOKBACK_DAYS = 60
MAX_PER_RUN = 30            # tags queued per workspace per sweep (cost cap); the rest wait for the next sweep
TASK = "marketing_tagging"
_FORMAT = {"REELS": "reel", "CAROUSEL_ALBUM": "carousel", "IMAGE": "photo", "VIDEO": "video", "STORY": "story"}
_KIND_FORMAT = {"reel": "reel", "carousel": "carousel", "story": "story", "post": "photo", "promo": "photo"}

SYSTEM = """You tag one marketing post, Reel or ad of a hospitality business so its results can be compared by element.
Read ONLY the text given (caption, slide or frame text, photo descriptions, ad copy). For every field pick the value the
text clearly shows; when the text does not show it, answer "unknown". Never guess from what such posts usually look like.
- hook_type: how the FIRST line opens: question, number ("3 mornings..."), pov ("POV: ..."), offer, moment (a time or
  scene), reveal ("wait for it", "the door opens"), statement, none.
- first_frame: the main subject of the first photo or frame in 1-3 words (from its description), else unknown.
- angle: the selling angle in 1-3 words (e.g. "romantic escape", "family road trip", "workation", "value").
- destination: the place named, else unknown. occasion: season or occasion named (e.g. "diwali", "monsoon"), else none.
- talent: who appears per the descriptions. text_overlay: yes only if slide/frame/overlay text exists.
- cta: what the reader is asked to do. pacing and audio: only from what the text says about them, else unknown.
Return the tags with the tool."""


def tool() -> dict:
    return {"name": "submit_tags", "description": "Return the creative tags.", "input_schema": _schema(CreativeTags)}


def _since() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)


def subjects(db: Session, tenant_id: str) -> list[tuple[str, str]]:
    """(subject_type, subject_id) for recent account media and ads with metrics."""
    from app.workers.tasks.instagram_insights_poll import InstagramPostSnapshot
    since = _since()
    media = [m for (m,) in db.query(InstagramPostSnapshot.media_id).filter(
        InstagramPostSnapshot.tenant_id == tenant_id, InstagramPostSnapshot.updated_at >= since)]
    ads = [a for (a,) in db.query(AdMetric.ad_id).filter(AdMetric.tenant_id == tenant_id,
                                                         AdMetric.date >= since.date()).distinct()]
    return [("ig_media", m) for m in media] + [("ad", a) for a in ads]


def queue_untagged(db: Session, tenant_id: str, limit: int = MAX_PER_RUN) -> list[str]:
    """Pending rows for subjects with no record yet (and failed AI rows, retried). Returns the row ids to tag."""
    have = {(r.subject_type, r.subject_id): r for r in db.query(MarketingCreativeTag).filter_by(tenant_id=tenant_id)}
    out = []
    for kind, sid in subjects(db, tenant_id):
        if len(out) >= limit:
            break
        row = have.get((kind, sid))
        if row is None:
            row = MarketingCreativeTag(tenant_id=tenant_id, subject_type=kind, subject_id=sid, status="pending")
            db.add(row)
            db.flush()
        elif not (row.status == "failed" and row.source == "ai"):
            continue
        row.status = "pending"
        out.append(row.id)
    return out


def _content_for(db: Session, tenant_id: str, row: MarketingCreativeTag):
    """(content item, approved payload) when HAIP made this post or ad, else (None, None)."""
    content_id = None
    if row.subject_type == "ig_media":
        for cid, ids in db.query(MarketingPublishAttempt.content_id, MarketingPublishAttempt.media_ids).filter(
                MarketingPublishAttempt.tenant_id == tenant_id, MarketingPublishAttempt.status == "published"):
            if row.subject_id in (ids or []):
                content_id = cid
                break
    else:
        from app.models.marketing_ads import MarketingAdDraft
        for d in db.query(MarketingAdDraft).filter(MarketingAdDraft.tenant_id == tenant_id, MarketingAdDraft.meta.isnot(None)):
            if (d.meta or {}).get("ad_id") == row.subject_id:
                content_id = d.content_id
                break
    if not content_id:
        return None, None
    item = content_svc.get_item(db, tenant_id, content_id)
    version = content_svc.get_version(db, tenant_id, item.approved_version_id or item.current_version_id)
    return item, (version.payload if version else {}) or {}


def context(db: Session, tenant_id: str, row: MarketingCreativeTag) -> tuple[str, dict]:
    """(text for the AI, fields known in code)."""
    from app.models.marketing import InstagramPostMetricDaily
    from app.services.marketing_render import frames
    from app.workers.tasks.instagram_insights_poll import InstagramPostSnapshot
    lines, known = [], {}
    item, payload = _content_for(db, tenant_id, row)
    if row.subject_type == "ig_media":
        snap = db.query(InstagramPostSnapshot).filter_by(tenant_id=tenant_id, media_id=row.subject_id).first()
        daily = (db.query(InstagramPostMetricDaily).filter_by(tenant_id=tenant_id, media_id=row.subject_id)
                 .order_by(InstagramPostMetricDaily.day.desc()).first())
        product = (daily.media_product_type if daily else None) or ""
        mtype = (snap.media_type if snap else None) or ""
        fmt = _FORMAT.get(product if product == "REELS" else mtype)
        if fmt:
            known["format"] = fmt
        if fmt in ("photo", "carousel"):
            known["length_band"] = "not_video"
        lines.append(f"Instagram {product or mtype or 'post'}")
        if snap and snap.caption:
            lines.append(f"Caption: {snap.caption[:1500]}")
    else:
        ad = db.query(AdEntity).filter_by(tenant_id=tenant_id, level="ad", entity_id=row.subject_id).first()
        c = (ad.creative or {}) if ad else {}
        lines.append(f"Meta ad: {ad.name if ad else row.subject_id}")
        for k in ("title", "body", "object_type", "call_to_action_type"):
            if c.get(k):
                lines.append(f"{k}: {str(c[k])[:800]}")
    if item is not None:
        row.content_id = item.id
        known["format"] = _KIND_FORMAT.get(item.kind, known.get("format", "unknown"))
        if item.kind != "reel":
            known["length_band"] = "not_video"
        lines.append(f"Made in HAIP as a {item.kind}: {item.title}")
        fr = frames(item.kind, payload)
        ids = [f["asset_id"] for f in fr if f["asset_id"]]
        assets = {a.id: a for a in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant_id, MediaAsset.id.in_(ids))} if ids else {}
        for n, f in enumerate(fr, start=1):
            a = assets.get(f["asset_id"])
            desc = (a.alt_text or (a.tags or {}).get("description")) if a is not None else None
            text = " / ".join(x for x in (f.get("headline"), f.get("sub"), f.get("cta")) if x)
            lines.append(f"Frame {n}: text: {text or '(none)'}; photo: {desc or '(no description)'}")
        if payload.get("caption") and not any(x.startswith("Caption:") for x in lines):
            lines.append(f"Caption: {str(payload['caption'])[:1500]}")
    return "\n".join(lines), known


def run_tag(db: Session, tenant_id: str, row_id: str) -> MarketingCreativeTag:
    """Celery only. A transient provider error raises ai.LLMTransientError (the task retries); anything else is kept on
    the row as failed. An owner-corrected row is left alone."""
    row = db.query(MarketingCreativeTag).filter_by(id=row_id, tenant_id=tenant_id).one()
    if row.source == "owner" or row.status == "ready":
        return row
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    row.prompt_version = get_version(TASK)
    text, known = context(db, tenant_id, row)
    try:
        data, raw, provider = ai._call(TASK, tenant_id, SYSTEM, text, tool())
        usage_service.record_llm(db, tenant_id, ai.MODULE, raw, provider=provider, ref_type="marketing_creative_tag",
                                 ref_id=row.id)
        tags = normalise(CreativeTags.model_validate({k: v for k, v in data.items() if v is not None}).model_dump())
        row.tags, row.model, row.status, row.error = {**tags, **known}, raw.get("model"), "ready", None
    except ValidationError as exc:
        row.status, row.error = "failed", f"The AI's tags did not fit the list: {ai._errors(exc)}"[:2000]
    except ValueError as exc:
        row.status, row.error = "failed", str(exc)[:2000]
    log.info("marketing_tagged", tenant_id=tenant.id, row_id=row.id, status=row.status)
    return row


def correct(db: Session, tenant_id: str, row_id: str, patch: dict, actor_id: str) -> MarketingCreativeTag:
    row = db.query(MarketingCreativeTag).filter_by(id=row_id, tenant_id=tenant_id).first()
    if row is None:
        raise MarketingError(404, "not_found", "No such tag record in this workspace.")
    try:
        changes = CreativeTagsPatch.model_validate(patch).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise MarketingError(422, "bad_tags", "Pick values from the lists.", [ai._errors(exc)])
    before = dict(row.tags or {})
    row.tags = normalise(CreativeTags.model_validate({**CreativeTags().model_dump(), **before, **changes}).model_dump())
    row.source, row.status, row.error = "owner", "ready", None
    row.corrected_by, row.corrected_at = actor_id, datetime.now(timezone.utc)
    append_audit(db, tenant_id=tenant_id, action="marketing.tags.corrected", actor_user_id=actor_id,
                 target_type="marketing_creative_tag", target_id=row.id,
                 payload={"before": {k: before.get(k) for k in changes}, "after": changes})
    return row


def as_dict(r: MarketingCreativeTag) -> dict:
    return {"id": r.id, "subject_type": r.subject_type, "subject_id": r.subject_id, "content_id": r.content_id,
            "tags": r.tags, "status": r.status, "source": r.source, "error": r.error, "model": r.model,
            "prompt_version": r.prompt_version, "corrected_at": r.corrected_at, "updated_at": r.updated_at}


def tags_by_subject(db: Session, tenant_id: str) -> dict[tuple[str, str], dict]:
    return {(r.subject_type, r.subject_id): r.tags for r in db.query(MarketingCreativeTag).filter(
        MarketingCreativeTag.tenant_id == tenant_id, MarketingCreativeTag.status == "ready")
        if r.tags}


def get(db: Session, tenant_id: str, row_id: str) -> Optional[MarketingCreativeTag]:
    return db.query(MarketingCreativeTag).filter_by(id=row_id, tenant_id=tenant_id).first()
