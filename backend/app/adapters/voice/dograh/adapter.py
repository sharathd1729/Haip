"""Dograh voice AI webhook adapter."""
import hashlib
import hmac
from urllib.parse import urlparse

from app.schemas.dograh import DograhCallPayload

# Allowed domains for recording URL SSRF protection.
_ALLOWED_RECORDING_HOSTS = frozenset({
    "cdn.dograh.com",
    "recordings.dograh.com",
    "storage.dograh.com",
})


class DograhAdapter:
    """Adapter for Dograh voice AI webhook events."""

    def verify_webhook_signature(
        self,
        payload: bytes,
        headers: dict,
        secret: str,
    ) -> bool:
        """
        Verify x-dograh-signature (HMAC-SHA256) against per-tenant secret.
        Returns False if secret is empty — unsigned webhooks are always rejected.
        Uses hmac.compare_digest to prevent timing attacks.
        """
        if not secret:
            return False
        signature = headers.get("x-dograh-signature", "")
        if not signature:
            return False
        # Strip optional "sha256=" prefix
        if signature.startswith("sha256="):
            signature = signature[7:]
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    def parse_call_completed_webhook(self, payload: dict) -> DograhCallPayload:
        """Parse and validate Dograh call.completed webhook payload."""
        return DograhCallPayload(**payload)

    def validate_recording_url(self, url: str) -> bool:
        """
        Return True only for HTTPS URLs from known Dograh CDN domains.
        Prevents SSRF via attacker-controlled recording_url.
        """
        if not url:
            return False
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.netloc in _ALLOWED_RECORDING_HOSTS
