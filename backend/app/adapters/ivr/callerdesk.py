import hashlib
import hmac
import httpx
from app.adapters.ivr.base import IVRAdapter, CallWebhookPayload
from app.core.config import settings


class CallerDeskAdapter(IVRAdapter):
    """CallerDesk IVR adapter for Ratha."""

    BASE_URL = "https://api.callerdesk.io/v1"

    def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool:
        """CallerDesk sends X-CallerDesk-Signature as HMAC-SHA256."""
        secret = settings.CALLERDESK_WEBHOOK_SECRET
        if not secret:
            return True  # Skip verification in dev if secret not set

        signature = headers.get("x-callerdesk-signature", "")
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    def parse_call_webhook(self, payload: dict) -> CallWebhookPayload:
        """
        CallerDesk call-completed webhook shape:
        {
            "call_id": "CD-123",
            "direction": "inbound",
            "caller_id_number": "+919876543210",
            "did_number": "+918012345678",
            "agent_number": "+919012345678",
            "duration": 240,
            "recording_url": "https://cdn.callerdesk.io/...",
            "start_time": "2024-01-15T10:00:00Z",
            "end_time": "2024-01-15T10:04:00Z"
        }
        """
        direction = payload.get("direction", "inbound").lower()
        if direction == "inbound":
            from_number = payload.get("caller_id_number", "")
            to_number = payload.get("did_number", "")
        else:
            from_number = payload.get("did_number", "")
            to_number = payload.get("caller_id_number", "")

        return CallWebhookPayload(
            ivr_call_id=payload["call_id"],
            direction=direction,
            from_number=self._normalize_phone(from_number),
            to_number=self._normalize_phone(to_number),
            duration_seconds=int(payload.get("duration", 0)),
            recording_url=payload.get("recording_url", ""),
            agent_number=self._normalize_phone(payload.get("agent_number", "")),
            started_at=payload.get("start_time", ""),
            ended_at=payload.get("end_time", ""),
            provider="callerdesk",
            raw=payload,
        )

    async def initiate_click_to_call(self, agent_number: str, guest_number: str) -> str:
        """POST to CallerDesk click-to-call API."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/click-to-call",
                headers={
                    "Authorization": f"Bearer {settings.CALLERDESK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "account_sid": settings.CALLERDESK_ACCOUNT_SID,
                    "agent_number": agent_number,
                    "customer_number": guest_number,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("call_id", "")

    async def fetch_recording(self, recording_url: str) -> bytes:
        """Download recording from CallerDesk CDN."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                recording_url,
                headers={"Authorization": f"Bearer {settings.CALLERDESK_API_KEY}"},
                timeout=60,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.content

    def _normalize_phone(self, phone: str) -> str:
        """Ensure E.164 format."""
        if not phone:
            return ""
        phone = phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+91" + phone.lstrip("0")
        return phone
