"""
Shared object-storage helper for inbound media persisted server-side
(WhatsApp media, per WhatsApp module Phase 1 T1.2). Mirrors the existing
R2/S3 pattern already used for call recordings (workers/tasks/call_ingest.py,
api/v1/endpoints/calls.py's _get_recording_url) rather than inventing a
second convention -- same boto3-against-AWS_S3_ENDPOINT_URL client setup,
same tenant-scoped key prefix.
"""
import boto3
from botocore.config import Config
from app.core.config import settings
import structlog

log = structlog.get_logger()


def _s3_client():
    kwargs: dict = dict(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )
    if settings.AWS_S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
        # Path-style addressing -- virtual-hosted-style (boto3's default)
        # breaks TLS cert validation against R2's endpoint.
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    return boto3.client("s3", **kwargs)


def upload_media(tenant_id: str, message_id: str, content: bytes, content_type: str, extension: str = "") -> str:
    """Upload inbound media bytes, return the storage key (not a URL --
    URLs must be generated on read via get_presigned_media_url, since
    Meta's own media URLs are short-lived and we don't want a second,
    accidentally-long-lived link floating around)."""
    suffix = f".{extension}" if extension else ""
    s3_key = f"{tenant_id}/whatsapp/{message_id}/media{suffix}"
    s3 = _s3_client()
    put_kwargs = dict(
        Bucket=settings.S3_BUCKET_NAME,
        Key=s3_key,
        Body=content,
        ContentType=content_type,
    )
    # SSE-KMS is an AWS S3 API feature R2 doesn't implement -- only send it
    # against real AWS S3, i.e. when no custom endpoint is configured.
    if settings.KMS_KEY_ID and not settings.AWS_S3_ENDPOINT_URL:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID
    s3.put_object(**put_kwargs)
    log.info("whatsapp_media_stored", tenant_id=tenant_id, message_id=message_id, s3_key=s3_key)
    return s3_key


def upload_personal_whatsapp_media(
    tenant_id: str, session_id: str, message_id: str, content: bytes, content_type: str, extension: str = "",
) -> str:
    """Store a photo/video/voice note/document that came through an agent's personal WhatsApp bridge, return the storage key.
    Same bucket and Cloudflare R2 endpoint as every other file (AWS_S3_ENDPOINT_URL), tenant-prefixed, one object per message
    so a re-delivered message simply overwrites itself. Read it back with get_presigned_media_url."""
    safe_id = "".join(c for c in message_id if c.isalnum() or c in "-_")[:80] or "msg"
    suffix = f".{extension}" if extension else ""
    s3_key = f"{tenant_id}/whatsapp_personal/{session_id}/{safe_id}{suffix}"
    put_kwargs = dict(Bucket=settings.S3_BUCKET_NAME, Key=s3_key, Body=content, ContentType=content_type)
    if settings.KMS_KEY_ID and not settings.AWS_S3_ENDPOINT_URL:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID
    _s3_client().put_object(**put_kwargs)
    log.info("whatsapp_personal_media_stored", tenant_id=tenant_id, session_id=session_id, s3_key=s3_key, bytes=len(content))
    return s3_key


def upload_ivr_greeting(
    tenant_id: str, content: bytes, content_type: str, extension: str = "mp3", kind: str = "greeting",
) -> str:
    """Upload a client-provided IVR audio recording, return the storage
    key. One file per tenant per `kind` -- a fixed key (no message/upload
    id in the path) so a re-upload/re-generate simply overwrites the old
    file rather than accumulating orphaned recordings that need separate
    cleanup. `kind` is "greeting" (plays before dialing agents) or
    "voicemail" (plays instead of dialing, see webhooks_vobiz.py)."""
    s3_key = f"{tenant_id}/ivr/{kind}.{extension}"
    s3 = _s3_client()
    put_kwargs = dict(
        Bucket=settings.S3_BUCKET_NAME,
        Key=s3_key,
        Body=content,
        ContentType=content_type,
    )
    if settings.KMS_KEY_ID and not settings.AWS_S3_ENDPOINT_URL:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID
    s3.put_object(**put_kwargs)
    log.info("ivr_greeting_stored", tenant_id=tenant_id, s3_key=s3_key)
    return s3_key


def upload_user_avatar(
    tenant_id: str, user_id: str, content: bytes, content_type: str, extension: str = "jpg",
) -> str:
    """Upload a staff member's avatar photo, return the storage key. Fixed
    key per (tenant, user) -- a re-upload overwrites the old file, same
    convention as upload_ivr_greeting. Guests have no equivalent -- no
    self-service mechanism for a guest to supply a photo."""
    s3_key = f"{tenant_id}/users/{user_id}/avatar.{extension}"
    s3 = _s3_client()
    put_kwargs = dict(
        Bucket=settings.S3_BUCKET_NAME,
        Key=s3_key,
        Body=content,
        ContentType=content_type,
    )
    if settings.KMS_KEY_ID and not settings.AWS_S3_ENDPOINT_URL:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID
    s3.put_object(**put_kwargs)
    log.info("user_avatar_stored", tenant_id=tenant_id, user_id=user_id, s3_key=s3_key)
    return s3_key


def upload_knowledge_file(
    tenant_id: str, upload_id: str, content: bytes, content_type: str, filename: str,
) -> str:
    """Upload a document a tenant provided to train the AI concierge's
    knowledge base (rate card, brochure, T&Cs, etc.), return the storage
    key. One key per upload (upload_id, not a fixed per-tenant path like
    the avatar/IVR helpers above) -- a tenant can upload many documents
    over time and each must stay individually retrievable, not overwrite
    the last one."""
    safe_name = filename.replace("/", "_").replace("\\", "_")[:200] or "document"
    s3_key = f"{tenant_id}/knowledge/{upload_id}/{safe_name}"
    s3 = _s3_client()
    put_kwargs = dict(
        Bucket=settings.S3_BUCKET_NAME,
        Key=s3_key,
        Body=content,
        ContentType=content_type,
    )
    if settings.KMS_KEY_ID and not settings.AWS_S3_ENDPOINT_URL:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID
    s3.put_object(**put_kwargs)
    log.info("knowledge_file_stored", tenant_id=tenant_id, upload_id=upload_id, s3_key=s3_key)
    return s3_key


def upload_wa_template_media(tenant_id: str, content: bytes, content_type: str, extension: str) -> str:
    """Upload the image/video/PDF a WhatsApp template header uses, return the
    storage key. One key per upload (a template can be edited to use a
    different file without overwriting one another template still points at)."""
    import uuid
    s3_key = f"{tenant_id}/wa_templates/{uuid.uuid4().hex}.{extension}"
    s3 = _s3_client()
    put_kwargs = dict(
        Bucket=settings.S3_BUCKET_NAME,
        Key=s3_key,
        Body=content,
        ContentType=content_type,
    )
    if settings.KMS_KEY_ID and not settings.AWS_S3_ENDPOINT_URL:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID
    s3.put_object(**put_kwargs)
    log.info("wa_template_media_stored", tenant_id=tenant_id, s3_key=s3_key)
    return s3_key


def get_presigned_media_url(s3_key: str, expires_in: int = 3600) -> str | None:
    """Generate a time-limited download URL for a stored media object.
    Returns None on any failure -- never let a presign error break message
    rendering, the caller falls back to showing no media."""
    if not s3_key:
        return None
    try:
        s3 = _s3_client()
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=expires_in,
        )
    except Exception as exc:
        log.warning("media_presign_failed", s3_key=s3_key, error=str(exc))
        return None


def upload_marketing_media(tenant_id: str, content: bytes, content_type: str, extension: str) -> str:
    """Store a Marketing Studio library image (an upload or a rendered creative), return the storage key.
    One key per asset; the media_assets row holds the metadata. Read back with get_presigned_media_url."""
    import uuid
    s3_key = f"{tenant_id}/marketing/{uuid.uuid4().hex}.{extension}"
    s3 = _s3_client()
    put_kwargs = dict(
        Bucket=settings.S3_BUCKET_NAME,
        Key=s3_key,
        Body=content,
        ContentType=content_type,
    )
    if settings.KMS_KEY_ID and not settings.AWS_S3_ENDPOINT_URL:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID
    s3.put_object(**put_kwargs)
    log.info("marketing_media_stored", tenant_id=tenant_id, s3_key=s3_key)
    return s3_key
