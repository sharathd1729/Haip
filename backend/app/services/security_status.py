"""What Settings › Security may claim, read from the running configuration (never hard-coded).

The page used to print fixed text: "AES-256 + KMS per tenant", "MFA required for Owner", a lockout and a device limit
that no code enforces, and key statuses typed into the page ("ANTHROPIC_API_KEY: Configured", "AWS_ACCESS_KEY_ID:
Missing") that matched nothing. Every claim here is derived from settings or code; only key NAMES and set / missing /
not used are returned, never a value.
"""

from __future__ import annotations

import os

from app.core.config import settings


def storage() -> dict:
    """Where call recordings and other files go, and how they are encrypted at rest (media_storage puts every object)."""
    endpoint = (settings.AWS_S3_ENDPOINT_URL or "").lower()
    has_creds = bool(settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY)
    if not has_creds:
        return {
            "provider": "not_configured",
            "encryption": "none",
            "text": "File storage is not configured: recordings and media cannot be saved.",
        }
    if endpoint:
        r2 = "r2.cloudflarestorage.com" in endpoint
        # SSE-KMS is only sent to real AWS S3 (media_storage); R2 encrypts every object at rest with its own keys.
        return {
            "provider": "cloudflare_r2" if r2 else "s3_compatible",
            "encryption": "provider_default" if r2 else "unknown",
            "text": (
                "Cloudflare R2, encrypted at rest by Cloudflare (AES-256, keys managed by Cloudflare)"
                if r2
                else "S3-compatible storage; encryption at rest depends on that provider"
            ),
        }
    if settings.KMS_KEY_ID:
        return {
            "provider": "aws_s3",
            "encryption": "aws_kms",
            "region": settings.AWS_REGION,
            "text": f"AWS S3 ({settings.AWS_REGION}), encrypted with one AWS KMS key for the whole server",
        }
    return {
        "provider": "aws_s3",
        "encryption": "s3_default",
        "region": settings.AWS_REGION,
        "text": f"AWS S3 ({settings.AWS_REGION}), S3's default encryption (no KMS key set)",
    }


def _transcription_provider() -> str:
    from app.adapters.transcription import _auto_detect_transcription

    return settings.TRANSCRIPTION_PROVIDER or _auto_detect_transcription()


def keys() -> list[dict]:
    """Server keys by name: set | missing | not_used (an optional provider this server does not use)."""
    stt = _transcription_provider()
    s3_endpoint = bool(settings.AWS_S3_ENDPOINT_URL)

    def row(name: str, value: str, used: bool = True, note: str = "") -> dict:
        status = "set" if value else ("missing" if used else "not_used")
        return {"name": name, "status": status, "note": note}

    return [
        row("ENCRYPTION_KEY", os.environ.get("ENCRYPTION_KEY", ""), note="encrypts integration credentials"),
        row(
            "AWS_ACCESS_KEY_ID",
            settings.AWS_ACCESS_KEY_ID,
            note="file storage key (Cloudflare R2)" if s3_endpoint else "file storage key (AWS S3)",
        ),
        row(
            "KMS_KEY_ID",
            settings.KMS_KEY_ID,
            used=not s3_endpoint,
            note="not used with Cloudflare R2" if s3_endpoint else "S3 encryption key",
        ),
        row("NVIDIA_API_KEY", settings.NVIDIA_API_KEY, note="most AI tasks"),
        row("GEMINI_API_KEY", settings.GEMINI_API_KEY, note="guest replies + fallback"),
        row("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY, used=False, note="not in the live AI routing"),
        row("SARVAM_API_KEY", settings.SARVAM_API_KEY, used=stt == "sarvam", note="call transcription"),
        row("GROQ_API_KEY", settings.GROQ_API_KEY, used=stt == "groq", note="call transcription"),
        row("DEEPGRAM_API_KEY", settings.DEEPGRAM_API_KEY, used=stt == "deepgram", note="call transcription"),
    ]


def status(user) -> dict:
    return {
        "storage": storage(),
        "transcription_provider": _transcription_provider(),
        "keys": keys(),
        "session": {
            "access_token_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
            "refresh_token_days": settings.REFRESH_TOKEN_EXPIRE_DAYS,
            # middleware/rate_limit.py _STRICT_AUTH: no account lockout and no device limit exist in code
            "login_rate_limit": "10 sign-in attempts a minute per IP address",
            # login() asks for a code only when the user has turned MFA on; no role is forced to
            "mfa_rule": "A code is asked at sign-in for everyone who has turned on two-step sign-in. No role is forced to.",
            "mfa_enabled_for_you": bool(getattr(user, "is_mfa_enabled", False)),
        },
        "legacy_webhook_verify_token_allowed": bool(settings.ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN),
    }
