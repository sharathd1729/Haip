"""Files an agent attaches in the inbox composer (WhatsApp only: the Instagram send task has no media path).

Upload (``POST /conversations/{id}/attachments``) checks the file's first bytes, never its name or browser type, against
WhatsApp's limits (photo JPEG/PNG <= 5 MB, video MP4 <= 16 MB, audio <= 16 MB, PDF <= 100 MB) and stores it at
``{tenant_id}/inbox_uploads/{uuid}.{ext}``. The send endpoint then takes that key as ``media_url``; the send task signs a
fresh link for Meta at send time (send_whatsapp: only this workspace's own keys), and the thread presigns it on read.
"""

from __future__ import annotations

import os
import re

FOLDER = "inbox_uploads"
MB = 1024 * 1024
MAX_BYTES = 100 * MB  # the largest type (PDF)
SNIFF_BYTES = 16

# extension -> (kind, content type, size cap)
_TYPES = {
    "jpg": ("image", "image/jpeg", 5 * MB),
    "png": ("image", "image/png", 5 * MB),
    "mp4": ("video", "video/mp4", 16 * MB),
    "m4a": ("audio", "audio/mp4", 16 * MB),
    "mp3": ("audio", "audio/mpeg", 16 * MB),
    "aac": ("audio", "audio/aac", 16 * MB),
    "ogg": ("audio", "audio/ogg", 16 * MB),
    "amr": ("audio", "audio/amr", 16 * MB),
    "pdf": ("document", "application/pdf", 100 * MB),
}
LIMIT_HINT = "Use a JPEG or PNG photo (5 MB), an MP4 video (16 MB), an audio file (16 MB) or a PDF (100 MB)."


def sniff(head: bytes) -> str | None:
    """The extension the file's first bytes prove, or None when it is not a type WhatsApp takes."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head[4:8] == b"ftyp":  # ISO media: an M4A brand is audio, anything else (isom, mp41, mp42, avc1) video
        return "m4a" if head[8:12] in (b"M4A ", b"M4B ") else "mp4"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    if head[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return "aac"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"#!AMR"):
        return "amr"
    return None


def describe(ext: str) -> tuple[str, str, int]:
    """(kind, content type, size cap) for a sniffed extension."""
    return _TYPES[ext]


def clean_filename(name: str | None, ext: str) -> str:
    base = re.sub(r"[\x00-\x1f/\\]", "", os.path.basename(name or "")).strip()[:120]
    return base or f"file.{ext}"


def store(tenant_id: str, content: bytes, ext: str) -> str:
    import uuid

    from app.services.media_storage import _put

    key = f"{tenant_id}/{FOLDER}/{uuid.uuid4().hex}.{ext}"
    _put(key, content, _TYPES[ext][1])
    return key


def kind_for_key(tenant_id: str, key: str) -> str | None:
    """The media kind of an inbox upload key, or None when the key is not this workspace's inbox upload."""
    m = re.fullmatch(rf"{re.escape(tenant_id)}/{FOLDER}/[0-9a-f]{{32}}\.([a-z0-9]+)", key or "")
    return _TYPES[m.group(1)][0] if m and m.group(1) in _TYPES else None
