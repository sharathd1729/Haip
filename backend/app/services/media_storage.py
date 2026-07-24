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
