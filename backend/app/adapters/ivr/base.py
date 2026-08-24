from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class CallWebhookPayload:
    """Normalized call-completed webhook from any IVR provider."""
    ivr_call_id: str
    direction: str              # inbound / outbound
    from_number: str            # E.164
    to_number: str              # E.164 (virtual/DID number)
    duration_seconds: int
    recording_url: str          # Provider-hosted URL (signed, short-lived)
    agent_number: str           # Agent's personal mobile that was bridged
    started_at: str             # ISO datetime
    ended_at: str               # ISO datetime
    provider: str               # callerdesk / acefone
    raw: dict                   # Original payload for audit
    ivr_dial_status: str = ""   # completed/busy/failed/cancel/timeout/no-answer -- Vobiz Dial callbackUrl only


class IVRAdapter(ABC):
    """Abstract adapter for IVR providers."""

    @abstractmethod
    def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool:
        """Verify that webhook came from the provider (HMAC or token check)."""
        pass

    @abstractmethod
    def parse_call_webhook(self, payload: dict) -> CallWebhookPayload:
        """Parse provider-specific webhook into normalized payload."""
        pass

    @abstractmethod
    async def initiate_click_to_call(self, agent_number: str, guest_number: str) -> str:
        """Trigger click-to-call. Returns provider call ID."""
        pass

    @abstractmethod
    async def fetch_recording(self, recording_url: str) -> bytes:
        """Download recording MP3/WAV from provider CDN."""
        pass
