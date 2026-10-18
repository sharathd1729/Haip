"""Research analyst (agency phase B): competitors, their public numbers, and a brief the strategist uses.

Data sources, kept apart and labelled:
  * source='api'    -- Business Discovery through the workspace's Facebook Login connection (integration
                       kind 'instagram_fb'). Deleted when that connection is removed (Meta Platform Terms).
  * source='manual' -- posts a person pasted in (link + what they read off the app). Never fetched by us:
                       Instagram forbids scraping, so a pasted link is stored as text, not visited.
The measured block (followers, engagement, formats, cadence) is computed here; the AI only interprets it.
"""
from datetime import datetime
from statistics import median
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.encryption import decrypt_credentials
from app.core.prompt_versions import get_version
from app.models.integration import Integration
from app.models.marketing import (MarketingCompetitor, MarketingCompetitorPost, MarketingCompetitorSnapshot,
                                  MarketingResearchBrief)
from app.models.tenant import Tenant
from app.schemas.marketing import CompetitorIn, CompetitorPostIn, ResearchBrief
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

FB_KIND = "instagram_fb"
MAX_COMPETITORS = 15
TOP_POSTS = 8


# ── Competitors ─────────────────────────────────────────────────────────────────────────────────────────────────────

def list_competitors(db: Session, tenant_id: str) -> list[MarketingCompetitor]:
    return (db.query(MarketingCompetitor).filter_by(tenant_id=tenant_id, active=1)
            .order_by(MarketingCompetitor.created_at.asc()).all())


def add_competitor(db: Session, tenant_id: str, data: CompetitorIn, actor_id: str) -> MarketingCompetitor:
    existing = db.query(MarketingCompetitor).filter_by(tenant_id=tenant_id, handle=data.handle).first()
    if existing is not None:
        if existing.active:
            raise MarketingError(409, "duplicate", f"@{data.handle} is already on the list.")
        existing.active, existing.display_name, existing.notes = 1, data.display_name, data.notes
        _manual_followers(db, tenant_id, existing.id, data.followers)
        return existing
    if len(list_competitors(db, tenant_id)) >= MAX_COMPETITORS:
        raise MarketingError(422, "too_many", f"Track at most {MAX_COMPETITORS} competitors.")
    comp = MarketingCompetitor(tenant_id=tenant_id, handle=data.handle, display_name=data.display_name, notes=data.notes,
                               created_by=actor_id)
    db.add(comp)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="marketing.competitor.added", actor_user_id=actor_id,
                 target_type="marketing_competitor", target_id=comp.id, payload={"handle": data.handle})
    _manual_followers(db, tenant_id, comp.id, data.followers)
    return comp


def _manual_followers(db: Session, tenant_id: str, competitor_id: str, followers: Optional[int]) -> None:
    if followers is not None:
        db.add(MarketingCompetitorSnapshot(tenant_id=tenant_id, competitor_id=competitor_id, source="manual",
                                           followers_count=followers))


def remove_competitor(db: Session, tenant_id: str, competitor_id: str, actor_id: str) -> None:
    comp = _competitor(db, tenant_id, competitor_id)
    comp.active = 0
    append_audit(db, tenant_id=tenant_id, action="marketing.competitor.removed", actor_user_id=actor_id,
                 target_type="marketing_competitor", target_id=comp.id, payload={"handle": comp.handle})


def _competitor(db: Session, tenant_id: str, competitor_id: str) -> MarketingCompetitor:
    comp = db.query(MarketingCompetitor).filter_by(id=competitor_id, tenant_id=tenant_id).first()
    if comp is None:
        raise MarketingError(404, "not_found", "No such competitor.")
    return comp


def add_manual_post(db: Session, tenant_id: str, competitor_id: str, data: CompetitorPostIn, actor_id: str) -> MarketingCompetitorPost:
    comp = _competitor(db, tenant_id, competitor_id)
    post = MarketingCompetitorPost(tenant_id=tenant_id, competitor_id=comp.id, source="manual", permalink=data.permalink,
                                   caption=data.caption, media_type=data.media_type, like_count=data.like_count,
                                   comments_count=data.comments_count, posted_at=data.posted_at, note=data.note,
                                   created_by=actor_id)
    db.add(post)
    db.flush()
    return post


# ── Facebook Login connection + Business Discovery ──────────────────────────────────────────────────────────────────

def fb_connection(db: Session, tenant_id: str) -> Optional[Integration]:
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind=FB_KIND).first()


def snapshot_competitors(db: Session, tenant_id: str, *, discover=None) -> dict:
    """One Business Discovery call per active competitor. Returns counts; stops at a refused token."""
    from app.adapters.instagram import business_discovery as bd

    discover = discover or bd.discover
    integ = fb_connection(db, tenant_id)
    if integ is None or integ.status != "active":
        return {"skipped": "Facebook connection not set up", "done": 0, "failed": 0}
    creds = decrypt_credentials(integ.credentials_kms_blob) if integ.credentials_kms_blob else {}
    token, ig_user = creds.get("access_token"), (integ.config or {}).get("ig_user_id")
    if not token or not ig_user:
        return {"skipped": "Facebook connection is missing its token or Instagram account", "done": 0, "failed": 0}
    done = failed = 0
    for comp in list_competitors(db, tenant_id):
        try:
            data = discover(token, ig_user, comp.handle)
        except bd.DiscoveryError as exc:
            db.add(MarketingCompetitorSnapshot(tenant_id=tenant_id, competitor_id=comp.id, source="api", error=str(exc)[:500]))
            failed += 1
            if exc.kind == "bad_token":
                integ.status = "error"
                cfg = dict(integ.config or {})
                cfg["last_error"] = str(exc)[:300]
                integ.config = cfg
                break
            if exc.kind == "rate_limited":
                break
            continue
        db.add(MarketingCompetitorSnapshot(tenant_id=tenant_id, competitor_id=comp.id, source="api",
                                           followers_count=data.get("followers_count"), media_count=data.get("media_count")))
        for m in data.get("media", []):
            if not m.get("id"):
                continue
            post = (db.query(MarketingCompetitorPost)
                    .filter_by(tenant_id=tenant_id, competitor_id=comp.id, source="api", media_id=m["id"]).first())
            if post is None:
                post = MarketingCompetitorPost(tenant_id=tenant_id, competitor_id=comp.id, source="api", media_id=m["id"])
                db.add(post)
            post.permalink, post.caption = m.get("permalink"), (m.get("caption") or "")[:2200]
            post.media_type, post.posted_at = m.get("media_type"), m.get("timestamp")
            post.like_count, post.comments_count = m.get("like_count"), m.get("comments_count")
        db.flush()
        done += 1
    return {"done": done, "failed": failed}


def disconnect_fb(db: Session, tenant_id: str, actor_id: str) -> dict:
    """Remove the Facebook connection and every piece of data that came through it (manual entries stay)."""
    integ = fb_connection(db, tenant_id)
    snaps = db.query(MarketingCompetitorSnapshot).filter_by(tenant_id=tenant_id, source="api").delete(synchronize_session=False)
    posts = db.query(MarketingCompetitorPost).filter_by(tenant_id=tenant_id, source="api").delete(synchronize_session=False)
    if integ is not None:
        integ.status, integ.credentials_kms_blob = "disconnected", None
    append_audit(db, tenant_id=tenant_id, action="marketing.instagram_fb.disconnected", actor_user_id=actor_id,
                 target_type="integration", target_id=integ.id if integ else None,
                 payload={"deleted_snapshots": snaps, "deleted_posts": posts})
    return {"deleted_snapshots": snaps, "deleted_posts": posts}


# ── Measured brief + AI reading ─────────────────────────────────────────────────────────────────────────────────────

def _weeks_between(stamps: list[str]) -> Optional[float]:
    times = []
    for s in stamps:
        try:
            times.append(datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00")))
        except (ValueError, AttributeError):
            continue
    if len(times) < 2:
        return None
    span = (max(times) - min(times)).total_seconds() / 604800
    return round((len(times) - 1) / span, 2) if span > 0 else None


def measured(db: Session, tenant_id: str) -> dict:
    out = []
    for comp in list_competitors(db, tenant_id):
        snap = (db.query(MarketingCompetitorSnapshot)
                .filter(MarketingCompetitorSnapshot.tenant_id == tenant_id, MarketingCompetitorSnapshot.competitor_id == comp.id,
                        MarketingCompetitorSnapshot.followers_count.isnot(None))
                .order_by(MarketingCompetitorSnapshot.created_at.desc()).first())
        followers = snap.followers_count if snap is not None else None
        followers_source = snap.source if snap is not None else None
        posts = db.query(MarketingCompetitorPost).filter_by(tenant_id=tenant_id, competitor_id=comp.id).all()
        rows = []
        for p in posts:
            eng = (p.like_count or 0) + (p.comments_count or 0) if (p.like_count is not None or p.comments_count is not None) else None
            rows.append({"source": p.source, "permalink": p.permalink, "media_type": p.media_type, "posted_at": p.posted_at,
                         "caption": (p.caption or "")[:200], "engagement": eng, "note": p.note,
                         "engagement_rate": round(eng / followers, 4) if eng is not None and followers else None})
        rates = [r["engagement_rate"] for r in rows if r["engagement_rate"] is not None]
        engs = [r["engagement"] for r in rows if r["engagement"] is not None]
        formats: dict[str, int] = {}
        for r in rows:
            if r["media_type"]:
                formats[r["media_type"]] = formats.get(r["media_type"], 0) + 1
        top = sorted([r for r in rows if r["engagement"] is not None], key=lambda r: r["engagement"], reverse=True)[:TOP_POSTS]
        out.append({"handle": comp.handle, "name": comp.display_name, "followers": followers,
                    "followers_source": followers_source, "posts_known": len(rows),
                    "median_engagement": median(engs) if engs else None,
                    "manual_posts": sum(1 for r in rows if r["source"] == "manual"),
                    "median_engagement_rate": round(median(rates), 4) if rates else None,
                    "posts_per_week": _weeks_between([r["posted_at"] for r in rows if r["source"] == "api" and r["posted_at"]]),
                    "formats": formats, "top_posts": top})
    return {"source_note": "api = Instagram Business Discovery (public counts only, no reach); manual = pasted by a person",
            "competitors": out}


def run_brief(db: Session, tenant: Tenant, actor_id: Optional[str]) -> MarketingResearchBrief:
    from app.services import marketing_ai_service as ai
    from app.services import marketing_prompts as prompts
    from pydantic import ValidationError

    data = measured(db, tenant.id)
    brief = MarketingResearchBrief(tenant_id=tenant.id, measured=data, status="pending", created_by=actor_id,
                                   prompt_version=get_version("marketing_research"))
    db.add(brief)
    db.flush()
    known = {p["permalink"] for c in data["competitors"] for p in c["top_posts"] if p.get("permalink")}
    if not any(c["posts_known"] for c in data["competitors"]):
        brief.status, brief.error = "failed", "No competitor posts yet. Add competitors and paste a few of their posts, or connect Facebook."
        return brief
    try:
        own = ai.measured_snapshot(db, tenant.id)
        user = (f"Business facts:\n{ai._facts(db, tenant)}\n\nOUR measured baseline:\n{own.get('baseline')}\n\n"
                f"COMPETITORS (measured):\n{data}")
        out, raw, provider = ai._call("marketing_research", tenant.id, ai._system(prompts.RESEARCH_SYSTEM, tenant), user,
                                      prompts.RESEARCH_TOOL)
        from app.services import usage_service
        usage_service.record_llm(db, tenant.id, "marketing_studio", raw, provider=provider, ref_type="marketing_research_brief",
                                 ref_id=brief.id)
        assessment = ResearchBrief.model_validate(out).model_dump(mode="json")
        for theme in assessment["themes"]:
            theme["examples"] = [e for e in theme["examples"] if e in known]     # only links that exist in the data
        brief.assessment, brief.model, brief.status, brief.error = assessment, raw.get("model"), "ready", None
    except ValidationError as exc:
        brief.status, brief.error = "failed", f"The AI's answer did not fit the research format: {ai._errors(exc)}"
    except ValueError as exc:
        brief.status, brief.error = "failed", str(exc)
    return brief


def latest_brief(db: Session, tenant_id: str) -> Optional[MarketingResearchBrief]:
    return (db.query(MarketingResearchBrief).filter_by(tenant_id=tenant_id, status="ready")
            .order_by(MarketingResearchBrief.created_at.desc()).first())
