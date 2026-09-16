"""
Shared webhook signature verification for all Meta platform webhooks
(WhatsApp, Instagram, etc.).

Design:
- Production: startup already refuses to start if META_APP_SECRET is missing
  (enforced in config.py).  If somehow reached without a secret → 401.
- Development/test: if secret is absent, log a loud WARNING per request and
  allow through so local dev still works without Meta credentials.
- Always use hmac.compare_digest (constant-time) to prevent timing attacks.
- Accepts raw bytes so FastAPI body streaming is not disturbed.
"""

import hashlib
import hmac as _hmac
from fastapi import HTTPException
import structlog

log = structlog.get_logger()


def verify_meta_signature(body: bytes, signature_header: str, env: str, secret: str) -> None:
    """
    Verify the X-Hub-Signature-256 header from a Meta webhook request.

    Args:
        body:             Raw request body bytes.
        signature_header: Value of the X-Hub-Signature-256 header.
        env:              Current ENVIRONMENT value (used for dev-vs-prod logic).
        secret:           META_APP_SECRET value.

    Raises:
        HTTPException(401) on any failure when the secret is configured.
        In dev with no secret: logs a warning and returns normally.
    """
    if not secret:
        if env == "production":
            # Should never reach here (config.py blocks startup), but
            # be fail-closed as defense in depth.
            log.error("webhook_signature_check_failed", reason="META_APP_SECRET missing in production")
            raise HTTPException(status_code=401, detail="Webhook not authenticated")
        # Development / test: warn loudly but allow through
        log.warning(
            "webhook_signature_skipped",
            reason="META_APP_SECRET not set — all webhooks accepted without verification",
        )
        return

    if not signature_header or not signature_header.startswith("sha256="):
        log.warning("webhook_missing_signature_header")
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    expected = "sha256=" + _hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()

    if not _hmac.compare_digest(expected, signature_header):
        log.warning("webhook_signature_mismatch", env=env)
        raise HTTPException(status_code=401, detail="Webhook signature verification failed")


def verify_meta_signature_any(
    body: bytes, signature_header: str, env: str, secrets: list[tuple[str, str]],
) -> str:
    """Like verify_meta_signature, but accepts a match against ANY of several
    secrets we hold. Returns the label of the secret that matched.

    `secrets` is a list of (label, secret); blank secrets are ignored.

    Why: the Instagram webhook used to verify against the per-tenant
    app_secret alone, falling back to META_APP_SECRET only when the tenant
    value was *empty*. A *wrong* tenant value -- one mistyped or mis-copied
    field on the reconnect form -- therefore rejected every inbound DM even
    though the server held the correct secret. Confirmed live on Ratha
    (16-Sep-2026): a reconnect overwrote a working secret and every webhook
    from then on logged webhook_signature_mismatch while Meta kept
    delivering, so the inbox went silent.

    Accepting any held secret does not weaken verification: forging a
    request still requires knowing one of our own secrets.
    """
    candidates = [(label, s) for label, s in secrets if s]

    if not candidates:
        # Preserve the single-secret semantics exactly: fail closed in
        # production, allow-with-warning in development.
        verify_meta_signature(body, signature_header, env, "")
        return "none"

    if not signature_header or not signature_header.startswith("sha256="):
        log.warning("webhook_missing_signature_header")
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    for label, secret in candidates:
        expected = "sha256=" + _hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if _hmac.compare_digest(expected, signature_header):
            return label

    log.warning("webhook_signature_mismatch", env=env, tried=[label for label, _ in candidates])
    raise HTTPException(status_code=401, detail="Webhook signature verification failed")
