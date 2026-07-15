"""Meta WhatsApp Cloud API outbound client."""
import httpx
from typing import Optional
from urllib.parse import urlparse
from app.core.config import settings
import structlog

log = structlog.get_logger()

WA_BASE = "https://graph.facebook.com/v20.0"

# SSRF protection for inbound media downloads (T1.2). The WhatsApp Cloud
# API's media-id lookup (GET /{media_id}) returns a short-lived download
# URL on Meta's own lookaside/CDN hosts -- same family Instagram's
# attachment payloads use (see adapters/instagram/meta_graph.py). Domain
# suffix allowlist, not exact-match, since these are dynamically numbered
# subdomains (e.g. scontent-bom2-1.cdninstagram.com, lookaside.fbsbx.com).
#
# NOTE: lookaside.fbsbx.com is Meta's long-documented WhatsApp media
# redirect host; the fbcdn.net/cdninstagram.com suffixes are included on
# the same trust basis as Instagram's existing allowlist, but per the
# build plan this should be verified against a live WhatsApp webhook
# payload before being fully relied on in production -- flagged, not
# guessed blind.
_ALLOWED_MEDIA_HOST_SUFFIXES = (
    "lookaside.fbsbx.com",
    ".fbcdn.net",
    "fbcdn.net",
    ".cdninstagram.com",
    "cdninstagram.com",
)


def validate_whatsapp_media_url(url: str) -> bool:
    """Return True only for HTTPS URLs whose host is on Meta's media-host allowlist."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    host = parsed.netloc.split("@")[-1].split(":")[0].lower()
    return any(host == s.lstrip(".") or host.endswith(s) for s in _ALLOWED_MEDIA_HOST_SUFFIXES)


class MetaCloudAdapter:
    def __init__(self, phone_number_id: str, access_token: str):
        self.phone_number_id = phone_number_id
        self.access_token = access_token

    async def send_text(self, to: str, body: str) -> dict:
        url = f"{WA_BASE}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        return await self._post(url, payload)

    async def send_template(self, to: str, template_name: str, language_code: str = "en_US", components: Optional[list] = None) -> dict:
        url = f"{WA_BASE}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components or [],
            },
        }
        return await self._post(url, payload)

    async def send_image(self, to: str, url: str, caption: str = "") -> dict:
        url_ = f"{WA_BASE}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": {"link": url, "caption": caption},
        }
        return await self._post(url_, payload)

    async def send_video(self, to: str, url: str, caption: str = "") -> dict:
        url_ = f"{WA_BASE}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "video",
            "video": {"link": url, "caption": caption},
        }
        return await self._post(url_, payload)

    async def send_audio(self, to: str, url: str) -> dict:
        url_ = f"{WA_BASE}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "audio",
            "audio": {"link": url},
        }
        return await self._post(url_, payload)

    async def send_document(self, to: str, url: str, filename: str = "", caption: str = "") -> dict:
        url_ = f"{WA_BASE}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "document",
            "document": {"link": url, "filename": filename or "document", "caption": caption},
        }
        return await self._post(url_, payload)

    async def mark_read(self, message_id: str) -> dict:
        url = f"{WA_BASE}/{self.phone_number_id}/messages"
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        return await self._post(url, payload)

    async def _post(self, url: str, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def fetch_media(self, media_id: str) -> tuple[bytes, str]:
        """
        Download inbound media by its Meta media ID. WhatsApp Cloud API
        webhooks never include a direct URL -- only a media_id -- so this
        is a two-step fetch: resolve the id to a short-lived (~5min),
        token-gated download URL, then fetch it immediately with the same
        bearer token (the URL itself is not fetchable without auth).

        Returns (content_bytes, mime_type). Caller is responsible for
        validating the resolved download URL's domain (SSRF allowlist)
        before this second fetch, since it originates from Meta's API
        response, not directly from the inbound webhook payload, but is
        still an external URL being dereferenced.
        """
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            meta_resp = await client.get(f"{WA_BASE}/{media_id}", headers=headers)
            meta_resp.raise_for_status()
            meta = meta_resp.json()
            download_url = meta.get("url", "")
            mime_type = meta.get("mime_type", "application/octet-stream")

            if not validate_whatsapp_media_url(download_url):
                raise ValueError(f"Media download URL failed SSRF allowlist check: host={httpx.URL(download_url).host if download_url else '(empty)'}")

            file_resp = await client.get(download_url, headers=headers)
            file_resp.raise_for_status()
            return file_resp.content, mime_type


def get_wa_adapter(phone_number_id: str, access_token: str) -> MetaCloudAdapter:
    return MetaCloudAdapter(phone_number_id=phone_number_id, access_token=access_token)
