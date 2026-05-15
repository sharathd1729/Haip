import hashlib
import hmac
import httpx
from app.adapters.ivr.base import IVRAdapter, CallWebhookPayload
from app.core.config import settings


class AcefoneAdapter(IVRAdapter):
    """Acefone (Servetel) IVR adapter for Jade Hospitainment."""

    BASE_URL = "https://api.acefone.com/v1"

    def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool:
        secret = settings.ACEFONE_WEBHOOK_SECRET
        if not secret:
            return True

        signature = headers.get("x-acefone-signature", "")
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    def parse_call_webhook(self, payload: dict) -> CallWebhookPayload:
        """
        Acefone call-completed webhook shape:
        {
            "unique_id": "ACE-456",
            "call_type": "inbound",
            "caller_number": "+919876543210",
            "did_number": "+918012345678",
            "agent_number": "+919012345678",
            "call_duration": 240,
            "recording_url": "https://recordings.acefone.com/...",
            "start_stamp": "2024-01-15 10:00:00",
            "end_stamp": "2024-01-15 10:04:00"
        }
        """
        direction = "inbound" if payload.get("call_type", "inbound") == "inbound" else "outbound"

        return CallWebhookPayload(
            ivr_call_id=payload["unique_id"],
            direction=direction,
            from_number=self._normalize_phone(payload.get("caller_number", "")),
            to_number=self._normalize_phone(payload.get("did_number", "")),
            duration_seconds=int(payload.get("call_duration", 0)),
            recording_url=payload.get("recording_url", ""),
            agent_number=self._normalize_phone(payload.get("agent_number", "")),
            started_at=payload.get("start_stamp", "").replace(" ", "T") + "Z",
            ended_at=payload.get("end_stamp", "").replace(" ", "T") + "Z",
            provider="acefone",
            raw=payload,
        )

    async def initiate_click_to_call(self, agent_number: str, guest_number: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/click2call",
                headers={
                    "api_key": settings.ACEFONE_API_KEY,
                    "api_secret": settings.ACEFONE_API_SECRET,
                    "Content-Type": "application/json",
                },
                json={
                    "agent_number": agent_number,
                    "customer_number": guest_number,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("unique_id", "")

    async def fetch_recording(self, recording_url: str) -> bytes:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                recording_url,
                headers={
                    "api_key": settings.ACEFONE_API_KEY,
                    "api_secret": settings.ACEFONE_API_SECRET,
                },
                timeout=60,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.content

    def _normalize_phone(self, phone: str) -> str:
        if not phone:
            return ""
        phone = phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+91" + phone.lstrip("0")
        return phone
