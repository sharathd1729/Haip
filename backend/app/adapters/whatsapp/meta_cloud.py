"""Meta WhatsApp Cloud API outbound client."""
import httpx
from typing import Optional
from app.core.config import settings
import structlog

log = structlog.get_logger()

WA_BASE = "https://graph.facebook.com/v20.0"


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


def get_wa_adapter(phone_number_id: str, access_token: str) -> MetaCloudAdapter:
    return MetaCloudAdapter(phone_number_id=phone_number_id, access_token=access_token)
