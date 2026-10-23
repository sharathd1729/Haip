"""The producer (studio plan phase 4): drafts built in CODE from what the owner already approved elsewhere, then the
normal photo picker and approval. Nothing here calls an AI or posts anything.

  * Template Reel from photos: 2-5 library photos, a caption line on each, 6-15 seconds, 9:16, brand kit and cover
    (poster) frame by the existing ffmpeg/Pillow renderer (marketing_reel: stills get a slow zoom). Hyperframes (a Node
    renderer) was not added: the VPS image already renders reels with ffmpeg, so a second renderer would duplicate it.
  * One brief -> several pieces: each of the brief's Reel scripts becomes a Reel draft (its shots as clip slots with
    the shot description as `shot_note`), the first script ALSO as a trial Reel with the second hook as its opening (to
    test openings: Instagram shows trial Reels to non-followers first), plus a carousel from the hooks and a story from
    the posting plan. 3-5 distinct pieces per theme; library photos/clips are picked for empty slots.
  * Best posting time: marketing_publish_service.suggest_time (this account's own reach by hour) already does it.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.marketing_research import MarketingStrategyDoc
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import marketing_content_service as content_svc
from app.services.marketing_content_service import MarketingError

MIN_PHOTOS, MAX_PHOTOS = 2, 5
MIN_SECONDS, MAX_SECONDS = 6, 15


def reel_from_photos(db: Session, tenant: Tenant, *, title: str, asset_ids: list[str], lines: list[str], caption: str,
                     actor_id: str, seconds: Optional[float] = None, trial: bool = False):
    ids = [a for a in asset_ids if a][:MAX_PHOTOS]
    if len(ids) < MIN_PHOTOS:
        raise MarketingError(422, "too_few_photos", f"Pick {MIN_PHOTOS} to {MAX_PHOTOS} library photos.")
    found = {a.id for a in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant.id, MediaAsset.id.in_(ids),
                                                       MediaAsset.status == "active",
                                                       MediaAsset.mime_type.in_(("image/jpeg", "image/png", "image/webp")))}
    if set(ids) - found:
        raise MarketingError(422, "asset_not_usable", "Use approved photos from this workspace's library.")
    each = seconds or max(MIN_SECONDS / len(ids), min(3.0, MAX_SECONDS / len(ids)))
    if not MIN_SECONDS <= each * len(ids) <= MAX_SECONDS:
        raise MarketingError(422, "bad_length", f"A template Reel runs {MIN_SECONDS}-{MAX_SECONDS} seconds.")
    clips = [{"media": {"asset_id": a}, "seconds": round(each, 1), "caption": (lines[i] if i < len(lines) else None) or None}
             for i, a in enumerate(ids)]
    payload = {"caption": caption, "clips": clips, "cover_text": (lines[0] if lines else None), "trial": trial}
    item = content_svc.create_item(db, tenant.id, kind="reel", title=title[:160], actor_id=actor_id, payload=payload)
    return item


def _clip_slots(brief: dict, shot_numbers: list[int]) -> list[dict]:
    shots = {s["n"]: s for s in brief.get("shots", [])}
    out = []
    for n in shot_numbers[:12]:
        s = shots.get(n)
        if s is None:
            continue
        out.append({"seconds": float(max(1, min(15, s.get("duration_s") or 3))), "caption": (s.get("on_screen_text") or None),
                    "shot_note": f"Shot {n}: {s.get('scene')} ({s.get('shot_size')}, {s.get('angle')}, {s.get('movement')})"[:200]})
    return out


def from_brief(db: Session, tenant: Tenant, doc_id: str, actor_id: str) -> list:
    """Draft content for a ready brief. Returns the created items (photos are picked from the library where it can)."""
    from app.services import marketing_photos as photos
    doc = db.query(MarketingStrategyDoc).filter_by(id=doc_id, tenant_id=tenant.id, kind="brief").first()
    if doc is None:
        raise MarketingError(404, "not_found", "No such brief.")
    if doc.status != "ready" or not doc.body:
        raise MarketingError(409, "not_ready", "The brief is not written yet.")
    if (doc.input or {}).get("produced"):
        raise MarketingError(409, "already_produced", "Drafts were already made from this brief.")
    b, theme = doc.body, (doc.input or {}).get("theme") or "Shoot"
    hooks = [h["text"] for h in b.get("hooks", [])]
    caption = (b.get("captions") or [b.get("focus") or theme])[0]
    code = ((doc.facts or {}).get("tracking") or {}).get("code")
    if code:
        caption = f"{caption}\n\nWhatsApp us with {code}"[:2200]
    made = []

    def make(kind: str, title: str, payload: dict):
        try:
            item = content_svc.create_item(db, tenant.id, kind=kind, title=f"{theme}: {title}"[:160], actor_id=actor_id,
                                           payload=payload)
        except MarketingError:
            return None                          # one piece that does not validate never blocks the others
        made.append(item)
        return item

    tests = []
    for i, r in enumerate(b.get("reels", [])[:3]):
        clips = _clip_slots(b, r.get("shots", []))
        if len(clips) < 2:
            continue
        first = make("reel", r.get("title") or f"Reel {i + 1}", {"caption": caption, "clips": clips,
                                                                 "cover_text": (hooks[i] if i < len(hooks) else None)})
        if i == 0 and len(hooks) > 1:            # the same Reel with another opening, posted as a trial Reel
            trial = make("reel", f"{r.get('title') or 'Reel'} (trial: second opening)",
                         {"caption": caption, "clips": [{**clips[0], "caption": hooks[1][:80]}, *clips[1:]],
                          "cover_text": hooks[1][:60], "trial": True})
            if first is not None and trial is not None:
                tests.append({"a": first.id, "b": trial.id, "a_hook": hooks[0], "b_hook": hooks[1]})
    if len(hooks) >= 2:
        make("carousel", "Carousel", {"caption": caption, "slides": [{"headline": h[:80]} for h in hooks[:5]]})
    plan = b.get("posting_plan") or []
    if plan:
        make("story", "Story", {"frames": [{"text": p.get("what", "")[:120]} for p in plan[:5]]})
    for item in made:
        photos.attach_photos(db, tenant, item.id, actor_id=actor_id)
    doc.input = {**(doc.input or {}), "produced": [i.id for i in made], "opening_tests": tests}
    return made
