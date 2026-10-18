"""Media library (models/media_asset.py): validated uploads and template-rendered creatives (owner decision D2).

Uploads are decoded and re-encoded by Pillow before storage, so what lands in R2 is a real image of an allowed type,
with EXIF (including GPS) stripped. Creatives are the tenant's own photo + brand-coloured text panel; no AI imagery.
"""
import hashlib
import io
import re
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import media_storage, usage_service

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
_FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}

# Instagram-friendly canvases.
TEMPLATES = {
    "portrait_panel": {"size": (1080, 1350), "label": "Feed 4:5, text panel at the bottom"},
    "square_panel": {"size": (1080, 1080), "label": "Feed 1:1, text panel at the bottom"},
    "story_panel": {"size": (1080, 1920), "label": "Story 9:16, text panel at the bottom"},
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_PANEL = "#1E7A5A"   # HAIP sea green; replaced by the tenant's branding_theme.primaryColor when set


class MediaError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _store(db: Session, tenant_id: str, data: bytes, mime: str, ext: str, size: tuple[int, int], *, source: str,
           actor_id: Optional[str], alt_text: Optional[str], property_id: Optional[str], provenance: Optional[dict],
           status: str = "active") -> MediaAsset:
    sha = hashlib.sha256(data).hexdigest()
    existing = db.query(MediaAsset).filter_by(tenant_id=tenant_id, sha256=sha, status="active").first()
    if existing is not None:
        return existing
    key = media_storage.upload_marketing_media(tenant_id, data, mime, ext)
    asset = MediaAsset(tenant_id=tenant_id, property_id=property_id, storage_key=key, mime_type=mime, bytes=len(data),
                       width=size[0], height=size[1], sha256=sha, alt_text=alt_text, source=source,
                       provenance=provenance, created_by=actor_id, status=status)
    db.add(asset)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="media.asset_added", actor_user_id=actor_id, target_type="media_asset",
                 target_id=asset.id, payload={"source": source, "bytes": len(data), "sha256": sha, "status": status})
    return asset


def add_upload(db: Session, tenant_id: str, raw: bytes, *, actor_id: str, alt_text: Optional[str] = None,
               property_id: Optional[str] = None) -> MediaAsset:
    if not raw:
        raise MediaError(422, "empty_file", "The file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise MediaError(413, "too_large", "Images must be 10 MB or smaller.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            if fmt not in _FORMATS:
                raise MediaError(415, "unsupported_type", "Use a JPEG, PNG or WebP image.")
            if probe.width * probe.height > MAX_PIXELS:
                raise MediaError(413, "too_many_pixels", "The image is too large in pixels.")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            if fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format=fmt, **({"quality": 90} if fmt in ("JPEG", "WEBP") else {}))   # no exif= -> metadata dropped
            size = img.size
    except MediaError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise MediaError(415, "not_an_image", "That file is not a readable image.")
    mime, ext = _FORMATS[fmt]
    return _store(db, tenant_id, out.getvalue(), mime, ext, size, source="upload", actor_id=actor_id,
                  alt_text=alt_text, property_id=property_id, provenance=None)


def add_generated(db: Session, tenant_id: str, raw: bytes, *, actor_id: Optional[str], provenance: dict) -> MediaAsset:
    """Store an AI-generated image. It lands as `pending_review`: not usable in content or creatives until approved."""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=92)      # re-encode: drops any metadata the provider embedded
            size = img.size
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise MediaError(502, "bad_generated_image", "The image service returned something that is not an image.")
    return _store(db, tenant_id, out.getvalue(), "image/jpeg", "jpg", size, source="ai", actor_id=actor_id,
                  alt_text=None, property_id=None, provenance=provenance, status="pending_review")


def _panel_colour(tenant: Tenant) -> str:
    theme = ((tenant.brand_config or {}).get("branding_theme") or {}) if tenant is not None else {}
    colour = theme.get("primaryColor") if isinstance(theme, dict) else None
    return colour if isinstance(colour, str) and _HEX.match(colour) else DEFAULT_PANEL


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:   # very old Pillow: fixed-size bitmap font
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    return lines


def render_creative(db: Session, tenant: Tenant, asset_id: str, *, template: str, headline: str,
                    subline: Optional[str], actor_id: str, read_bytes=None) -> MediaAsset:
    """Crop the photo to the template canvas and draw a brand-coloured panel with the text. Returns a new asset."""
    spec = TEMPLATES.get(template)
    if spec is None:
        raise MediaError(422, "unknown_template", f"Template must be one of {', '.join(TEMPLATES)}.")
    headline = (headline or "").strip()
    if not 1 <= len(headline) <= 80 or (subline and len(subline) > 120):
        raise MediaError(422, "text_length", "Headline 1-80 characters, subline at most 120.")
    src = db.query(MediaAsset).filter_by(id=asset_id, tenant_id=tenant.id, status="active").first()
    if src is None:
        raise MediaError(404, "asset_not_found", "No such image in this workspace.")
    raw = (read_bytes or _read_object)(src.storage_key)
    with Image.open(io.BytesIO(raw)) as img:
        canvas = ImageOps.fit(img.convert("RGB"), spec["size"], method=Image.Resampling.LANCZOS)
    w, h = canvas.size
    panel_h = int(h * 0.26)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, h - panel_h, w, h], fill=_panel_colour(tenant))
    pad = int(w * 0.07)
    big, small = _font(int(w * 0.062)), _font(int(w * 0.036))
    y = h - panel_h + int(panel_h * 0.16)
    for line in _wrap(draw, headline, big, w - 2 * pad, 2):
        draw.text((pad, y), line, font=big, fill="#FFFFFF")
        y += int(w * 0.075)
    for line in _wrap(draw, subline or "", small, w - 2 * pad, 2):
        draw.text((pad, y), line, font=small, fill="#FFFFFF")
        y += int(w * 0.048)
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=90)
    asset = _store(db, tenant.id, out.getvalue(), "image/jpeg", "jpg", canvas.size, source="template", actor_id=actor_id,
                   alt_text=src.alt_text, property_id=src.property_id,
                   provenance={"template": template, "from_asset_id": src.id, "headline": headline, "subline": subline})
    usage_service.record(db, tenant.id, module="marketing_studio", kind="creative_render", units=1,
                         ref_type="media_asset", ref_id=asset.id)
    return asset


def _read_object(key: str) -> bytes:
    from app.core.config import settings

    obj = media_storage._s3_client().get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
    body = obj["Body"].read(MAX_UPLOAD_BYTES * 2 + 1)
    if len(body) > MAX_UPLOAD_BYTES * 2:
        raise MediaError(413, "too_large", "Stored image is unexpectedly large.")
    return body
