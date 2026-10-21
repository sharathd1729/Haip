"""Photo choice for drafts: every slide, frame or post gets a real photo from the workspace's own library.

The copywriter describes the photo each slot needs (`media.alt_text`). The picker scores every approved library photo
against it: words shared with that description (strongest), words shared with the slide's text and the post title,
the same property, and photos not used recently or elsewhere in the same post. Deterministic and explainable, no AI call. A person can
swap any photo before approving; the choice is saved as a new version, so the approval covers the exact photos.
"""
import copy
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.marketing import MarketingContent, MarketingContentVersion
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import marketing_content_service as content_svc
from app.services.marketing_render import frames
from app.services.media_library_service import _panel_colour

SOURCE_TYPES = ("image/jpeg", "image/png", "image/webp")
RECENT_DAYS = 30
_WORD = re.compile(r"[a-zऀ-ॿ]{3,}")
_STOP = {"the", "and", "with", "for", "from", "our", "your", "this", "that", "into", "onto", "over", "photo", "image",
         "picture", "shot", "showing", "view", "of", "a", "an", "in", "on", "at", "near", "by"}


def _words(*texts: Optional[str]) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out |= {w for w in _WORD.findall((t or "").lower()) if w not in _STOP}
    return out


def library(db: Session, tenant_id: str) -> list[MediaAsset]:
    """Approved photos a post may use (AI images only once approved; rendered outputs never)."""
    return (db.query(MediaAsset)
            .filter(MediaAsset.tenant_id == tenant_id, MediaAsset.status == "active",
                    MediaAsset.mime_type.in_(SOURCE_TYPES))
            .order_by(MediaAsset.created_at.desc()).limit(500).all())


def recent_use(db: Session, tenant_id: str, *, exclude_item: Optional[str] = None) -> Counter:
    """How often each photo appears in content touched in the last RECENT_DAYS days (current versions only)."""
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    rows = (db.query(MarketingContent.kind, MarketingContentVersion.payload)
            .join(MarketingContentVersion, MarketingContentVersion.id == MarketingContent.current_version_id)
            .filter(MarketingContent.tenant_id == tenant_id, MarketingContent.updated_at >= since,
                    MarketingContent.status != "archived",
                    *( [MarketingContent.id != exclude_item] if exclude_item else []))
            .limit(300).all())
    used: Counter = Counter()
    for kind, payload in rows:
        used.update(f["asset_id"] for f in frames(kind, payload or {}) if f["asset_id"])
    return used


def score(asset: MediaAsset, want: set[str], *, property_id: Optional[str], uses: int, in_this_post: bool,
          context: frozenset[str] = frozenset()) -> float:
    """`want` = words of the slot's photo description; `context` = words of the slide text and title (weaker)."""
    have = _words(asset.alt_text)
    s = 4.0 * len(want & have) + 1.0 * len((context - want) & have)
    if property_id and asset.property_id == property_id:
        s += 2.0
    s -= 1.0 * min(uses, 5)
    if in_this_post:
        s -= 6.0                     # repeat a photo inside one post only when the library runs out
    return s


def pick(photos: list[MediaAsset], want: set[str], *, property_id: Optional[str], used: Counter,
         taken: set[str], context: frozenset[str] = frozenset()) -> Optional[MediaAsset]:
    if not photos:
        return None
    # Ties keep library order (newest first), so the result is stable for the same inputs.
    return max(photos, key=lambda a: score(a, want, property_id=property_id, uses=used.get(a.id, 0),
                                             in_this_post=a.id in taken, context=context))


def _slots(kind: str, payload: dict) -> list[dict]:
    """The dicts holding `media`, in posting order (the payload is edited in place through these)."""
    if kind == "carousel":
        return payload.get("slides", [])
    if kind == "story":
        return payload.get("frames", [])
    return [payload]


def fill(db: Session, tenant: Tenant, item: MarketingContent, payload: dict,
         photos: Optional[list[MediaAsset]] = None, used: Optional[Counter] = None) -> tuple[int, list[int]]:
    """Put a library photo into every empty slot of `payload` (in place) and fix the design colour.
    Returns (slots filled, 1-based positions whose photo shares no word with what the slot asked for)."""
    photos = library(db, tenant.id) if photos is None else photos
    used = recent_use(db, tenant.id, exclude_item=item.id) if used is None else used
    fr = frames(item.kind, payload)
    taken = {f["asset_id"] for f in fr if f["asset_id"]}
    filled, loose = 0, []
    for n, (slot, f) in enumerate(zip(_slots(item.kind, payload), fr), start=1):
        if f["asset_id"]:
            continue
        media = dict(slot.get("media") or {})
        want = _words(media.get("alt_text"))
        context = frozenset(_words(f["headline"], f["sub"], item.title))
        chosen = pick(photos, want, property_id=item.property_id, used=used, taken=taken, context=context)
        if chosen is None:
            break
        media["asset_id"] = chosen.id
        slot["media"] = media
        taken.add(chosen.id)
        used[chosen.id] += 1
        filled += 1
        if not (want | context) & _words(chosen.alt_text):
            loose.append(n)                             # filled so the post can go out, but a person should look
    design = dict(payload.get("design") or {})
    if not design.get("colour"):
        design["colour"] = _panel_colour(tenant)       # frozen into the version, so approval covers the colour
    design.setdefault("style", "photo" if item.kind == "post" and not payload.get("overlay_text") else "overlay")
    if design != payload.get("design"):
        payload["design"] = design
    return filled, loose


def attach_photos(db: Session, tenant: Tenant, item_id: str, *, actor_id: Optional[str] = None,
                  photos: Optional[list[MediaAsset]] = None, used: Optional[Counter] = None) -> int:
    """Save a new version with photos in every empty slot. Returns the number of slots filled (0 = nothing saved)."""
    item = content_svc.get_item(db, tenant.id, item_id)
    version = content_svc.get_version(db, tenant.id, item.current_version_id)
    if version is None or item.status not in ("draft", "rejected"):
        return 0
    payload = copy.deepcopy({k: v for k, v in (version.payload or {}).items() if k != "kind"})
    before = copy.deepcopy(payload)
    filled, loose = fill(db, tenant, item, payload, photos, used)
    if payload == before:
        return 0
    content_svc.add_version(db, tenant.id, item.id, payload, origin="ai", actor_id=actor_id,
                            note=_note(item.kind, filled, loose))
    return filled


def _note(kind: str, filled: int, loose: list[int]) -> str:
    if not filled:
        return "Design colour set"
    note = f"Photos chosen from the library ({filled})"
    if loose:
        where = {"carousel": "slide", "story": "frame"}.get(kind, "photo")
        note += (f"; no close match for {where}{'s' if len(loose) > 1 else ''} {', '.join(map(str, loose))}"
                 " - check or add a better photo")
    return note
