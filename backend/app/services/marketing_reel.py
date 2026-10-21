"""Reels from the property's own clips (agency M3): upload, cut, caption, cover frame. ffmpeg only, no music.

Clips. An upload is probed with ffprobe (a real video stream, 1-90 s, <= 100 MB) and remuxed WITHOUT re-encoding into an
MP4 with all metadata (GPS, device, chapters) and every audio track dropped: HAIP never posts a clip's own sound, so
recorded voices of guests or staff never leave the workspace and no licensed music is involved. The clip lands as an
active library asset (mime video/mp4, duration_ms set).

Reels. The approved payload is rendered deterministically: each clip (or still photo, with a slow zoom) is cut to its
seconds, scaled and cropped to 1080x1920 at 30 fps, its caption drawn by Pillow onto a transparent PNG and overlaid
(no font file or drawtext build needed), then the parts are joined. The cover is a frame of the cover clip with the
cover text drawn by the post renderer. Outputs are `derived` media assets keyed by the payload hash, so the approval
preview and the published reel are the same file. Runs in Celery (marketing_studio.render_reel) or the publisher,
never in a request handler.
"""
import hashlib
import io
import json
import os
import subprocess
import tempfile
from typing import Callable, Optional

import structlog
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import marketing_render as post_render
from app.services import media_library_service as library
from app.services.media_library_service import MediaError, _panel_colour, _store

log = structlog.get_logger()

REEL = (1080, 1920)
FPS = 30
REEL_VERSION = 1                       # bump when the cut or drawing changes, so old renders are not reused
MAX_CLIP_BYTES = 100 * 1024 * 1024
MAX_CLIP_SECONDS = 90
VIDEO_TYPES = ("video/mp4",)
STEP_TIMEOUT = 180                     # seconds per ffmpeg call
_CONTAINERS = ("mov", "mp4", "m4a", "3gp", "matroska", "webm")


def _run(args: list[str], *, timeout: int = STEP_TIMEOUT) -> subprocess.CompletedProcess:
    try:
        out = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        raise MediaError(503, "ffmpeg_missing", "Video tools are not installed on this server.")
    except subprocess.TimeoutExpired:
        raise MediaError(504, "video_timeout", "The video took too long to process.")
    if out.returncode != 0:
        log.warning("ffmpeg_failed", tool=args[0], stderr=out.stderr.decode("utf-8", "replace")[-400:])
        raise MediaError(422, "video_unreadable", "That video could not be processed. Use an MP4 or MOV clip.")
    return out


def probe(path: str) -> dict:
    """{duration_ms, width, height} of the first video stream, rotation applied. Raises MediaError if there is none."""
    out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path], timeout=30)
    try:
        info = json.loads(out.stdout or b"{}")
    except ValueError:
        raise MediaError(422, "video_unreadable", "That video could not be read.")
    fmt = (info.get("format") or {}).get("format_name") or ""
    video = next((s for s in info.get("streams") or [] if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    if video is None or not any(c in fmt.split(",") for c in _CONTAINERS):
        raise MediaError(415, "not_a_video", "Use an MP4 or MOV video clip.")
    try:
        seconds = float(video.get("duration") or (info.get("format") or {}).get("duration") or 0)
    except ValueError:
        seconds = 0.0
    w, h = int(video.get("width") or 0), int(video.get("height") or 0)
    rotation = next((int(sd.get("rotation", 0)) for sd in video.get("side_data_list") or [] if "rotation" in sd), 0)
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return {"duration_ms": int(seconds * 1000), "width": w, "height": h}


def add_clip(db: Session, tenant_id: str, raw: bytes, *, actor_id: str, alt_text: Optional[str] = None,
             property_id: Optional[str] = None) -> MediaAsset:
    """Validate and store one clip: video stream only, metadata stripped, no re-encode (fast enough for a request)."""
    if not raw:
        raise MediaError(422, "empty_file", "The file is empty.")
    if len(raw) > MAX_CLIP_BYTES:
        raise MediaError(413, "too_large", "Clips must be 100 MB or smaller.")
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, "in"), os.path.join(tmp, "clip.mp4")
        with open(src, "wb") as fh:
            fh.write(raw)
        meta = probe(src)
        if not 1000 <= meta["duration_ms"] <= MAX_CLIP_SECONDS * 1000:
            raise MediaError(422, "clip_length", f"Clips must be 1 to {MAX_CLIP_SECONDS} seconds long.")
        _run(["ffmpeg", "-y", "-v", "error", "-i", src, "-map", "0:v:0", "-c:v", "copy", "-an", "-sn", "-dn",
              "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", out], timeout=60)
        meta = probe(out)
        with open(out, "rb") as fh:
            data = fh.read()
    asset = _store(db, tenant_id, data, "video/mp4", "mp4", (meta["width"], meta["height"]), source="upload",
                   actor_id=actor_id, alt_text=alt_text, property_id=property_id, provenance={"clip": True})
    asset.duration_ms = meta["duration_ms"]
    return asset


def is_video(asset: Optional[MediaAsset]) -> bool:
    return asset is not None and (asset.mime_type or "").startswith("video/")


def frame_at(video: bytes, seconds: float) -> bytes:
    """One JPEG frame of a clip (the storyboard preview and the cover)."""
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, "in.mp4"), os.path.join(tmp, "f.jpg")
        with open(src, "wb") as fh:
            fh.write(video)
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, seconds):.2f}", "-i", src, "-frames:v", "1",
              "-q:v", "3", out], timeout=60)
        with open(out, "rb") as fh:
            return fh.read()


# ── Rendering ───────────────────────────────────────────────────────────────────────────────────────────────────────

def payload_sha(payload: dict) -> str:
    body = json.dumps({"v": REEL_VERSION, "clips": payload.get("clips"), "cover_text": payload.get("cover_text"),
                       "cover_clip": payload.get("cover_clip"), "design": payload.get("design")},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def caption_png(text: Optional[str], design: dict, logo: Optional[bytes]) -> bytes:
    """A transparent 1080x1920 layer: the clip's caption in a soft band above the Reels UI, plus the brand logo."""
    w, h = REEL
    layer = Image.new("RGBA", REEL, (0, 0, 0, 0))
    if logo and design.get("logo_position") in ("top_left", "top_right"):
        post_render._paste_logo(layer, logo, design["logo_position"])
    font = design.get("font")
    real = post_render.font_path(font, True) is not None
    line = post_render._drawable(text, real)
    if line:
        big = post_render._font(int(w * 0.062), font, True)
        d = ImageDraw.Draw(layer)
        lines = post_render._wrap(d, line, big, int(w * 0.8), 3)
        line_h = int(w * 0.078)
        top = int(h * 0.60)                          # clear of the caption and buttons Instagram draws at the bottom
        pad = int(w * 0.04)
        widths = [d.textlength(x, font=big) for x in lines]
        band = (int((w - max(widths)) / 2) - pad, top - pad, int((w + max(widths)) / 2) + pad,
                top + line_h * len(lines) + pad)
        d.rounded_rectangle(band, radius=int(w * 0.03), fill=(12, 12, 12, 150))
        accent = design.get("accent") or design.get("colour")
        if accent:
            d.rectangle([band[0], band[1], band[0] + int(w * 0.012), band[3]], fill=accent)
        for i, x in enumerate(lines):
            d.text((int((w - widths[i]) / 2), top + i * line_h), x, font=big, fill="#FFFFFF")
    out = io.BytesIO()
    layer.save(out, format="PNG")
    return out.getvalue()


_FIT = f"scale={REEL[0]}:{REEL[1]}:force_original_aspect_ratio=increase,crop={REEL[0]}:{REEL[1]},setsar=1"
_ENCODE = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def _segment(tmp: str, n: int, source: bytes, *, video: bool, start: float, seconds: float, layer: bytes) -> str:
    src, png, out = (os.path.join(tmp, f"s{n}.{'mp4' if video else 'img'}"), os.path.join(tmp, f"c{n}.png"),
                     os.path.join(tmp, f"seg{n}.mp4"))
    with open(src, "wb") as fh:
        fh.write(source)
    with open(png, "wb") as fh:
        fh.write(layer)
    frames = max(1, int(round(seconds * FPS)))
    if video:
        args = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{seconds:.2f}", "-i", src, "-i", png,
                "-filter_complex", f"[0:v]{_FIT},fps={FPS}[v];[v][1:v]overlay=0:0:eof_action=repeat[o]"]
    else:   # a still photo: a slow push-in (1.00 -> 1.08) over its seconds
        zoom = f"zoompan=z='min(1+0.08*on/{frames},1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={REEL[0]}x{REEL[1]}:fps={FPS}"
        args = ["ffmpeg", "-y", "-v", "error", "-i", src, "-i", png,
                "-filter_complex", f"[0:v]{_FIT},{zoom}[v];[v][1:v]overlay=0:0:eof_action=repeat[o]"]
    _run([*args, "-map", "[o]", "-frames:v", str(frames), *_ENCODE, out])
    return out


def _existing(db: Session, tenant_id: str, sha: str) -> tuple[Optional[MediaAsset], Optional[MediaAsset]]:
    rows = (db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant_id, MediaAsset.status == "derived",
                                        MediaAsset.mime_type == "video/mp4")
            .order_by(MediaAsset.created_at.desc()).limit(200).all())
    video = next((r for r in rows if (r.provenance or {}).get("reel_sha") == sha), None)
    if video is None:
        return None, None
    cover_id = (video.provenance or {}).get("cover_asset_id")
    cover = db.query(MediaAsset).filter_by(id=cover_id, tenant_id=tenant_id).first() if cover_id else None
    return video, cover


def find_render(db: Session, tenant: Tenant, payload: dict) -> tuple[Optional[MediaAsset], Optional[MediaAsset]]:
    return _existing(db, tenant.id, payload_sha(payload))


def render_reel(db: Session, tenant: Tenant, payload: dict, *,
                read_bytes: Optional[Callable[[str], bytes]] = None) -> tuple[MediaAsset, MediaAsset]:
    """(video, cover) for this payload, rendered once and reused. Raises MediaError on a missing or unapproved clip."""
    sha = payload_sha(payload)
    video, cover = _existing(db, tenant.id, sha)
    if video is not None and cover is not None:
        return video, cover
    design = dict(payload.get("design") or {})
    design.setdefault("colour", _panel_colour(tenant))
    fr, sources = post_render._sources(db, tenant, "reel", payload)
    read = read_bytes or library._read_object
    logo = post_render._logo_bytes(db, tenant, design, read)
    cache: dict[str, bytes] = {}
    clips = payload.get("clips") or []
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for n, (clip, f) in enumerate(zip(clips, fr)):
            src = sources[f["asset_id"]]
            if src.id not in cache:
                cache[src.id] = read(src.storage_key)
            seconds = float(clip.get("seconds") or 3)
            start = float(clip.get("start_s") or 0)
            if is_video(src) and src.duration_ms:
                length = src.duration_ms / 1000
                start = start if start < length - 0.5 else 0.0
                seconds = min(seconds, max(0.5, length - start))
            parts.append(_segment(tmp, n, cache[src.id], video=is_video(src), start=start, seconds=seconds,
                                  layer=caption_png(clip.get("caption"), design, logo)))
        listing = os.path.join(tmp, "parts.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            fh.writelines(f"file '{os.path.basename(p)}'\n" for p in parts)
        out = os.path.join(tmp, "reel.mp4")
        _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy",
              "-movflags", "+faststart", out])
        meta = probe(out)
        with open(out, "rb") as fh:
            data = fh.read()
        index = min(int(payload.get("cover_clip") or 0), len(parts) - 1)
        at = sum(float(c.get("seconds") or 3) for c in clips[:index]) + 0.4
        still = frame_at(data, at)
    cover_jpeg = post_render.draw(still, REEL, style="overlay" if payload.get("cover_text") else "photo",
                                  colour=design["colour"], headline=payload.get("cover_text"), sub=None, cta=None,
                                  accent=design.get("accent"), font=design.get("font"), logo=logo,
                                  logo_position=design.get("logo_position"))
    first = sources[fr[0]["asset_id"]]
    cover = _store(db, tenant.id, cover_jpeg, "image/jpeg", "jpg", REEL, source="template", actor_id=None,
                   alt_text=first.alt_text, property_id=first.property_id, status="derived",
                   provenance={"reel_cover": True, "reel_sha": sha})
    video = _store(db, tenant.id, data, "video/mp4", "mp4", REEL, source="template", actor_id=None,
                   alt_text=first.alt_text, property_id=first.property_id, status="derived",
                   provenance={"reel_version": REEL_VERSION, "reel_sha": sha, "cover_asset_id": cover.id,
                               "clips": [f["asset_id"] for f in fr]})
    video.duration_ms = meta["duration_ms"]
    db.flush()
    return video, cover
