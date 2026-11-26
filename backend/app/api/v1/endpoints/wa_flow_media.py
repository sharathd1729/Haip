"""POST /messaging/flows/media: the photo, video, audio or PDF a WhatsApp flow canvas "media" step sends.

Type is decided by the file's first bytes (never the name or the browser's content type), size by WhatsApp's limits.
Stored at ``<tenant>/wa_flows/<uuid>.<ext>``; saving a flow refuses any key outside this workspace's folder.
"""
import os
import re

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.v1.deps import require_roles
from app.models.user import User, UserRole

log = structlog.get_logger()
router = APIRouter(prefix="/messaging", tags=["messaging"])

_MB = 1024 * 1024
# magic bytes -> (kind, content type, extension, WhatsApp size cap)
_TYPES = {
    b"\xff\xd8\xff": ("image", "image/jpeg", "jpg", 5 * _MB),
    b"\x89PNG\r\n\x1a\n": ("image", "image/png", "png", 5 * _MB),
    b"%PDF-": ("document", "application/pdf", "pdf", 100 * _MB),
    b"OggS": ("audio", "audio/ogg", "ogg", 16 * _MB),
    b"ID3": ("audio", "audio/mpeg", "mp3", 16 * _MB),
    b"\xff\xfb": ("audio", "audio/mpeg", "mp3", 16 * _MB),
    b"\xff\xf3": ("audio", "audio/mpeg", "mp3", 16 * _MB),
    b"\xff\xf2": ("audio", "audio/mpeg", "mp3", 16 * _MB),
    b"\xff\xf1": ("audio", "audio/aac", "aac", 16 * _MB),
    b"\xff\xf9": ("audio", "audio/aac", "aac", 16 * _MB),
}
_MP4 = ("video", "video/mp4", "mp4", 16 * _MB)


def sniff(content: bytes):
    """(kind, content type, extension, cap) for a supported file, else None."""
    if content[4:8] == b"ftyp" and content[8:11] != b"M4A":   # MP4 video (an .m4a audio file shares the box)
        return _MP4
    return next((v for magic, v in _TYPES.items() if content.startswith(magic)), None)


@router.post("/flows/media")
def upload_flow_media(
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
):
    content = file.file.read(100 * _MB + 1)
    found = sniff(content)
    if not found:
        raise HTTPException(status_code=400, detail="Use a JPEG or PNG photo, an MP4 video, MP3/OGG/AAC audio or a PDF.")
    kind, content_type, ext, cap = found
    if len(content) > cap:
        raise HTTPException(status_code=400, detail=f"WhatsApp takes a {kind} up to {cap // _MB} MB. Use a smaller file.")
    from app.services.media_storage import get_presigned_media_url, upload_wa_flow_media

    key = upload_wa_flow_media(current_user.tenant_id, content, content_type, ext)
    name = re.sub(r"[\x00-\x1f/\\]", "", os.path.basename(file.filename or "")).strip()[:120] or f"file.{ext}"
    log.info("wa_flow_media_uploaded", tenant_id=current_user.tenant_id, kind=kind, bytes=len(content))
    return {"kind": kind, "key": key, "filename": name, "preview_url": get_presigned_media_url(key, expires_in=3600)}
