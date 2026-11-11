"""The HAIP Calls app (Android) as a call source, so its calls go through call_ingest like any IVR call.

Not a webhook provider: mobile_device_service builds the payload below from an authenticated device upload (number already
normalised to E.164) and queues call_ingest.process with ivr_provider "mobile_app". Recordings arrive separately (spec step 2).
"""
from app.adapters.ivr.base import CallWebhookPayload, IVRAdapter

PROVIDER = "mobile_app"


class MobileAppAdapter(IVRAdapter):
    def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool:
        return False   # never a webhook: uploads are authenticated by device token in the endpoint

    def parse_call_webhook(self, payload: dict) -> CallWebhookPayload:
        answered = bool(payload["answered"])
        return CallWebhookPayload(
            ivr_call_id=payload["ivr_call_id"],
            direction=payload["direction"],
            from_number=payload["from_number"],
            to_number=payload["to_number"],
            # The phone's own answered flag is the conclusive signal (call_status_service reads ivr_dial_status first);
            # an unanswered call's ring time is not talk time.
            duration_seconds=int(payload["duration_sec"]) if answered else 0,
            recording_url="",
            agent_number="",
            started_at=payload["started_at"],
            ended_at=payload["ended_at"],
            provider=PROVIDER,
            raw={},
            ivr_dial_status="completed" if answered else "no-answer",
            agent_id=payload.get("agent_id") or "",
        )

    async def initiate_click_to_call(self, agent_number: str, guest_number: str) -> str:
        raise NotImplementedError("The Calls app places calls from the phone's own dialer")

    async def fetch_recording(self, recording_url: str) -> bytes:
        raise NotImplementedError("Calls app recordings are uploaded by the device (spec step 2)")
