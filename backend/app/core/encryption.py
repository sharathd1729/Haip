"""
Symmetric encryption for integration credentials stored at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256). The key is a 32-byte URL-safe
base64 value stored in the ENCRYPTION_KEY environment variable.

Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import json
import os
from cryptography.fernet import Fernet, InvalidToken

_KEY_ENV = "ENCRYPTION_KEY"


def _get_fernet() -> Fernet:
    key = os.environ.get(_KEY_ENV, "")
    if not key:
        raise RuntimeError(
            f"'{_KEY_ENV}' environment variable is not set.\n"
            "Integration credentials cannot be stored safely without it.\n"
            "Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
            "Then set it in your .env file."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_credentials(data: dict) -> bytes:
    """Encrypt a credentials dict to bytes for storage in credentials_kms_blob."""
    f = _get_fernet()
    return f.encrypt(json.dumps(data).encode())


def decrypt_credentials(blob: bytes) -> dict:
    """Decrypt bytes from credentials_kms_blob back to a credentials dict."""
    if not blob:
        return {}
    f = _get_fernet()
    try:
        return json.loads(f.decrypt(blob).decode())
    except (InvalidToken, Exception):
        return {}


def get_credential(blob: bytes, key: str, default: str = "") -> str:
    """Convenience: decrypt blob and return a single key."""
    return decrypt_credentials(blob).get(key, default)
