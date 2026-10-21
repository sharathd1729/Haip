"""What actually gets posted: the approved payload's photos with its text drawn on, as JPEGs.

Instagram needs a public JPEG per image and shows only what is in the pixels, so a carousel slide's headline, a story
frame's text or a post's overlay line must be rendered onto the photo. Rendering is deterministic from the payload (its
`design` included), so the preview the approver sees is exactly what the publisher posts. Outputs are stored as
media_assets with status "derived": deduplicated by content hash, never listed in the photo library, never usable as
the source of another post.
"""
import functools
import io
import os
import unicodedata
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import media_library_service as library
from app.services.media_library_service import MediaError, _panel_colour, _store

FEED = (1080, 1350)       # 4:5, the tallest feed ratio Instagram keeps
STORY = (1080, 1920)      # 9:16
RENDER_VERSION = 2        # bump when the drawing changes, so old outputs are not reused (2: brand kit, M3)


def frames(kind: str, payload: dict) -> list[dict]:
    """One entry per image to post, in order: {asset_id, headline, sub, cta}."""
    def media(x):
        return ((x or {}).get("media") or {}).get("asset_id")
    if kind == "carousel":
        return [{"asset_id": media(s), "headline": s.get("headline"), "sub": s.get("body"), "cta": None}
                for s in payload.get("slides", [])]
    if kind == "story":
        return [{"asset_id": media(f), "headline": f.get("text"), "sub": None, "cta": f.get("cta")}
                for f in payload.get("frames", [])]
    if kind == "reel":       # the storyboard: one still per clip (the reel itself is services/marketing_reel.py)
        return [{"asset_id": media(c), "headline": c.get("caption"), "sub": None, "cta": None,
                 "at": float(c.get("start_s") or 0) + 0.3} for c in payload.get("clips", [])]
    if kind == "promo":
        return [{"asset_id": media(payload), "headline": payload.get("headline"),
                 "sub": payload.get("offer") or payload.get("body"), "cta": payload.get("cta")}]
    return [{"asset_id": media(payload), "headline": payload.get("overlay_text"), "sub": None, "cta": None}]


# Pillow's bundled font covers basic Latin only: dashes, the rupee sign and accented letters would draw as boxes.
_ASCII = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
                        "\u00a0": " ", "\u202f": " ", "\u20b9": "Rs "})


def _drawable(text: Optional[str], real_font: bool = False) -> str:
    """Text the font can draw. Pillow's bundled font: typographic dashes and spaces made plain, accents dropped
    (Kerala -> Kerala). A Noto font draws them, so only surrounding space is trimmed."""
    if real_font:
        return (text or "").strip()
    t = (text or "").translate(_ASCII)
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c)).strip()


# Brand-kit typefaces (agency M3). Debian's fonts-noto-core (backend/Dockerfile) puts them here; when a file is
# missing (local dev, tests) the bundled font is used, so a render never fails for want of a font.
FONT_DIRS = ("/usr/share/fonts/truetype/noto", "/usr/share/fonts/noto")
_FONT_FILES = {"sans": ("NotoSans-Bold.ttf", "NotoSans-Regular.ttf"),
               "serif": ("NotoSerif-Bold.ttf", "NotoSerif-Regular.ttf")}


@functools.lru_cache(maxsize=8)
def font_path(family: Optional[str], bold: bool) -> Optional[str]:
    names = _FONT_FILES.get(family or "")
    if not names:
        return None
    for d in FONT_DIRS:
        path = os.path.join(d, names[0 if bold else 1])
        if os.path.isfile(path):
            return path
    return None


def _font(size: int, family: Optional[str] = None, bold: bool = False):
    path = font_path(family, bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, line = (text or "").split(), [], ""
    for i, word in enumerate(words):
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            line = ""
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and len(" ".join(lines).split()) < len(words):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last + "…"
    return lines


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _paste_logo(canvas: Image.Image, logo: bytes, position: str) -> None:
    """The brand logo in a top corner, 16% of the width, transparency kept."""
    with Image.open(io.BytesIO(logo)) as raw:
        mark = raw.convert("RGBA")
    w, _ = canvas.size
    target = max(1, int(w * 0.16))
    mark = mark.resize((target, max(1, int(mark.height * target / max(1, mark.width)))), Image.Resampling.LANCZOS)
    margin = int(w * 0.05)
    x = margin if position == "top_left" else w - margin - mark.width
    canvas.paste(mark, (x, margin), mark)


def draw(photo: bytes, size: tuple[int, int], *, style: str, colour: str, headline: Optional[str], sub: Optional[str],
         cta: Optional[str], accent: Optional[str] = None, font: Optional[str] = None, logo: Optional[bytes] = None,
         logo_position: Optional[str] = None) -> bytes:
    """Pure function: photo bytes + text + design (+ brand kit) -> JPEG bytes."""
    with Image.open(io.BytesIO(photo)) as img:
        canvas = ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), size, method=Image.Resampling.LANCZOS,
                              centering=(0.5, 0.45))
    w, h = canvas.size
    if logo and logo_position in ("top_left", "top_right"):
        _paste_logo(canvas, logo, logo_position)
    real = font_path(font, True) is not None
    text = [_drawable(headline, real), _drawable(sub, real), _drawable(cta, real)]
    if style == "photo" or not any(text):
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=90)
        return out.getvalue()
    pad = int(w * 0.075)
    big, small, pill = _font(int(w * 0.066), font, True), _font(int(w * 0.038), font), _font(int(w * 0.034), font, True)
    probe = ImageDraw.Draw(canvas)
    head_lines = _wrap(probe, text[0], big, w - 2 * pad, 3)
    sub_lines = _wrap(probe, text[1], small, w - 2 * pad, 3)
    line_h, sub_h = int(w * 0.08), int(w * 0.052)
    block = len(head_lines) * line_h + (int(w * 0.02) + len(sub_lines) * sub_h if sub_lines else 0) \
        + (int(w * 0.105) if text[2] else 0)
    bottom = h - (int(h * 0.11) if size == STORY else pad)     # keep clear of the story reply bar
    top = bottom - block
    if style == "panel":
        band = Image.new("RGB", (w, h - top + pad), _hex(colour))
        canvas.paste(band, (0, top - pad))
        ink, bar, pill_fill, pill_ink = "#FFFFFF", accent or "#FFFFFF", accent or "#FFFFFF", "#FFFFFF" if accent else colour
    else:   # overlay: a dark fade under the text, brand-coloured accent bar
        fade_top = max(0, top - int(h * 0.22))
        fade = Image.new("L", (1, h - fade_top))
        for y in range(h - fade_top):
            fade.putpixel((0, y), int(185 * min(1.0, y / max(1, (top - fade_top)))))
        shade = Image.new("RGB", (w, h - fade_top), (12, 12, 12))
        canvas.paste(shade, (0, fade_top), fade.resize((w, h - fade_top)))
        ink, bar, pill_fill, pill_ink = "#FFFFFF", accent or colour, accent or colour, "#FFFFFF"
    d = ImageDraw.Draw(canvas)
    d.rectangle([pad, top - int(w * 0.035), pad + int(w * 0.09), top - int(w * 0.027)], fill=bar)
    y = top
    for line in head_lines:
        d.text((pad, y), line, font=big, fill=ink, stroke_width=1, stroke_fill=ink)
        y += line_h
    if sub_lines:
        y += int(w * 0.02)
        for line in sub_lines:
            d.text((pad, y), line, font=small, fill=ink)
            y += sub_h
    if text[2]:
        y += int(w * 0.03)
        tw = d.textlength(text[2], font=pill)
        bx = (pad, y, pad + int(tw) + int(w * 0.06), y + int(w * 0.07))
        d.rounded_rectangle(bx, radius=int(w * 0.035), fill=pill_fill)
        d.text((pad + int(w * 0.03), y + int(w * 0.017)), text[2], font=pill, fill=pill_ink)
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _sources(db: Session, tenant: Tenant, kind: str, payload: dict):
    fr = frames(kind, payload)
    ids = [f["asset_id"] for f in fr]
    if not ids or any(not a for a in ids):
        raise MediaError(422, "photo_missing", "Every slide or frame needs a photo from the library.")
    found = {a.id: a for a in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant.id, MediaAsset.id.in_(ids),
                                                         MediaAsset.status == "active")}
    if any(a not in found for a in ids):
        raise MediaError(422, "photo_unavailable", "A chosen photo is missing or not approved.")
    return fr, found


def _logo_bytes(db: Session, tenant: Tenant, design: dict, read: Callable[[str], bytes]) -> Optional[bytes]:
    """The logo frozen into the design. A logo that has since been archived fails the render: the approval covered
    a post with the logo, so it is not silently posted without it."""
    logo_id = design.get("logo_asset_id")
    if not logo_id or design.get("logo_position") in (None, "none"):
        return None
    logo = db.query(MediaAsset).filter_by(id=logo_id, tenant_id=tenant.id, status="active").first()
    if logo is None:
        raise MediaError(422, "logo_unavailable", "The brand logo in this design is no longer in the library.")
    return read(logo.storage_key)


def images(db: Session, tenant: Tenant, kind: str, payload: dict, *, scale: float = 1.0, limit: Optional[int] = None,
           read_bytes: Optional[Callable[[str], bytes]] = None) -> list[tuple[bytes, MediaAsset, dict]]:
    """(jpeg, source asset, frame) per image, drawn in memory. `scale` < 1 gives a smaller preview of the same design;
    `limit` draws only the first images (look variants)."""
    design = payload.get("design") or {}
    style = design.get("style") or "overlay"
    colour = design.get("colour") or _panel_colour(tenant)
    base = STORY if kind in ("story", "reel") else FEED
    size = (int(base[0] * scale), int(base[1] * scale))
    fr, sources = _sources(db, tenant, kind, payload)
    read = read_bytes or library._read_object
    logo = _logo_bytes(db, tenant, design, read)
    look = {"accent": design.get("accent"), "font": design.get("font"), "logo": logo,
            "logo_position": design.get("logo_position")}
    cache: dict[str, bytes] = {}
    out = []
    for f in fr[:limit] if limit else fr:
        src = sources[f["asset_id"]]
        if src.id not in cache:
            cache[src.id] = read(src.storage_key)
        photo = cache[src.id]
        if (src.mime_type or "").startswith("video/"):
            from app.services.marketing_reel import frame_at
            photo = frame_at(photo, f.get("at") or 0)
        out.append((draw(photo, size, style=style, colour=colour, headline=f["headline"], sub=f["sub"],
                         cta=f["cta"], **look), src, {**f, "style": style}))
    return out


def render(db: Session, tenant: Tenant, kind: str, payload: dict, *,
           read_bytes: Optional[Callable[[str], bytes]] = None) -> list[MediaAsset]:
    """The images to post for this payload, stored (or reused) as derived JPEG assets, in posting order.
    Raises MediaError if a frame has no photo or the photo is not an active library image."""
    size = STORY if kind == "story" else FEED
    return [_store(db, tenant.id, data, "image/jpeg", "jpg", size, source="template", actor_id=None,
                   alt_text=src.alt_text, property_id=src.property_id, status="derived",
                   provenance={"render_version": RENDER_VERSION, "from_asset_id": src.id, "style": f["style"],
                               "headline": f["headline"], "sub": f["sub"], "cta": f["cta"],
                               "kit": {k: (payload.get("design") or {}).get(k)
                                       for k in ("accent", "font", "logo_asset_id", "logo_position")}})
            for data, src, f in images(db, tenant, kind, payload, read_bytes=read_bytes)]
