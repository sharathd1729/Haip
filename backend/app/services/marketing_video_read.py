"""Read a Reel into the swipe file (studio plan phase 2): cut times by ffmpeg's scene detector (already in the image;
no PySceneDetect dependency needed), everything else by the workspace's vision model (adapters/vision, Gemini with
the video inline; the text LLM router has no video input). Pacing is computed from the cuts in code.

Runs in Celery only (`marketing_research.read_video`), only when the owner switched "video_reading" on, only on Reels
the collector kept a copy of (<= 20 MB), at most READS_PER_RUN per sweep.
"""
import re
import subprocess
import tempfile
from typing import Callable, Optional

import structlog
from sqlalchemy.orm import Session

from app.core.prompt_versions import get_version
from app.models.marketing import MarketingCompetitorPost
from app.models.marketing_research import MarketingSwipeItem
from app.models.tenant import Tenant

log = structlog.get_logger()

READS_PER_RUN = 5
_PTS = re.compile(r"pts_time:([0-9.]+)")
PROMPT = """You are reading a short vertical travel / hospitality video (an Instagram Reel) for a marketing swipe file.
Return JSON with exactly these keys:
{"hook_text": "the words said or shown in the first 3 seconds, or empty",
 "hook_type": "question|number|pov|offer|moment|reveal|statement|none",
 "first_frame": "main subject of the first frame, 1-3 words",
 "format": "talking_head|montage|pov_walkthrough|before_after|listicle|single_shot|other",
 "shots": [{"what": "short description", "size": "wide|medium|close", "movement": "static|pan|push_in|handheld|drone"}],
 "text_on_screen": ["each on-screen text line"],
 "cta": "what the viewer is asked to do, or none",
 "why_it_works": "one sentence, only from what is visible"}
Describe only what is in the video. At most 8 shots."""


def cut_times(video: bytes, *, threshold: float = 0.3, run: Optional[Callable] = None) -> list[float]:
    """Scene-change timestamps (seconds) from ffmpeg's `select=gt(scene,t)` + showinfo."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
        fh.write(video)
        path = fh.name
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-filter:v", f"select='gt(scene,{threshold})',showinfo",
           "-f", "null", "-"]
    try:
        out = (run or subprocess.run)(cmd, capture_output=True, text=True, timeout=90)
    finally:
        import os
        os.unlink(path)
    return [round(float(t), 2) for t in _PTS.findall(out.stderr or "")][:200]


def pacing(cuts: list[float], duration_s: Optional[float]) -> Optional[str]:
    if not duration_s:
        return None
    per_s = len(cuts) / duration_s
    return "fast" if per_s >= 0.5 else "medium" if per_s >= 0.2 else "slow"


def read_post(db: Session, tenant: Tenant, post_id: str, *, read_bytes: Optional[Callable[[str], bytes]] = None,
              describe: Optional[Callable] = None, cutter: Callable = cut_times) -> MarketingSwipeItem:
    from app.adapters import vision
    from app.services.media_library_service import _read_object
    post = db.query(MarketingCompetitorPost).filter_by(id=post_id, tenant_id=tenant.id).one()
    item = db.query(MarketingSwipeItem).filter_by(tenant_id=tenant.id, competitor_post_id=post.id).first()
    if item is None:
        item = MarketingSwipeItem(tenant_id=tenant.id, competitor_post_id=post.id, source_url=post.permalink, evidence="platform")
        db.add(item)
    if item.status == "ready":
        return item
    item.prompt_version = get_version("marketing_video_read")
    if not post.media_key:
        item.status, item.error = "failed", "No copy of the video was kept (the collector keeps Reels up to 20 MB)."
        return item
    try:
        video = (read_bytes or _read_object)(post.media_key)
        cuts = cutter(video)
        model = vision.get_model(vision.DEFAULT_MODEL)
        if describe is None:
            from app.adapters.vision import gemini
            describe = gemini.describe
        reading, meta = describe(model, video, PROMPT, mime_type="video/mp4")
    except Exception as exc:  # noqa: BLE001 -- recorded on the item; the next sweep does not retry a failed one
        item.status, item.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        return item
    item.reading = {k: reading.get(k) for k in ("hook_text", "hook_type", "first_frame", "format", "shots",
                                                 "text_on_screen", "cta", "why_it_works")}
    item.cut_times, item.pacing = cuts, pacing(cuts, post.duration_s)
    item.model, item.status, item.error = meta.get("model"), "ready", None
    from app.services import usage_service
    usage_service.record(db, tenant.id, module="marketing_studio", kind="video_read", units=1, provider=meta.get("provider"),
                         model=meta.get("model"), input_units=meta.get("input_tokens"), output_units=meta.get("output_tokens"),
                         ref_type="marketing_swipe_item", ref_id=item.id, meta={"est_cost_usd": meta.get("est_cost_usd")})
    return item


def to_read(db: Session, tenant_id: str, limit: int = READS_PER_RUN) -> list[str]:
    """Kept Reels with no swipe item yet, most viewed first."""
    done = {p for (p,) in db.query(MarketingSwipeItem.competitor_post_id).filter_by(tenant_id=tenant_id)}
    rows = (db.query(MarketingCompetitorPost).filter(MarketingCompetitorPost.tenant_id == tenant_id,
                                                     MarketingCompetitorPost.media_key.isnot(None))
            .order_by(MarketingCompetitorPost.views.desc()).limit(50).all())
    return [r.id for r in rows if r.id not in done][:limit]


def swipe_file(db: Session, tenant_id: str, limit: int = 50) -> list[dict]:
    rows = (db.query(MarketingSwipeItem).filter_by(tenant_id=tenant_id, status="ready")
            .order_by(MarketingSwipeItem.updated_at.desc()).limit(limit).all())
    return [{"id": r.id, "evidence": r.evidence, "source_url": r.source_url, "pacing": r.pacing, "cuts": len(r.cut_times or []),
             **(r.reading or {})} for r in rows]
