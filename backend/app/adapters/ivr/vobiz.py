import base64
import hashlib
import hmac
from urllib.parse import urlparse

import httpx

from app.adapters.ivr.base import IVRAdapter, CallWebhookPayload
from app.core.config import settings

# Confirmed live against a real recording callback: RecordFile/RecordUrl
# actually point at media.vobiz.ai (e.g.
# https://media.vobiz.ai/v1/Account/{auth_id}/Recording/{id}.mp3), not
# api.vobiz.ai as the docs implied -- api.vobiz.ai kept too since it's the
# documented general API host and may still serve some recording links.
_ALLOWED_RECORDING_HOSTS = frozenset({"api.vobiz.ai", "media.vobiz.ai"})


class VobizAdapter(IVRAdapter):
    """
    Vobiz IVR adapter — recording-only pass (no DTMF menu, no AI agent).

    Vobiz's inbound flow is a two-webhook cycle, unlike CallerDesk/Acefone/
    Mcube's single call-completed webhook:
      1. Answer URL webhook fires when the call arrives (CallUUID/From/To/
         CallStatus, no recording yet). HAIP replies with XML: dial the
         agent's mobile and record the whole session.
      2. When the (session-long) recording finishes, Vobiz POSTs to the
         separate callbackUrl with RecordUrl/RecordingDuration/CallUUID.

    parse_call_webhook() here expects the MERGED payload webhooks_vobiz.py
    builds by combining (1)'s cached from/to/direction with (2)'s
    recording/duration data, since CallWebhookPayload needs everything in
    one shot to match every other provider's shape.

    Unlike CallerDesk/Acefone/Mcube (one shared account per HAIP deployment,
    configured via server settings), Vobiz here is each client's own account
    -- auth_id/auth_token are per-tenant, passed in explicitly by the caller
    (see call_ingest.py's _do_fetch_recording) rather than read from global
    settings. The fallback to settings.VOBIZ_AUTH_ID/VOBIZ_AUTH_TOKEN only
    matters if those are ever set for a single-tenant deployment.
    """

    def __init__(self, auth_id: str = "", auth_token: str = ""):
        self.auth_id = auth_id or settings.VOBIZ_AUTH_ID
        self.auth_token = auth_token or settings.VOBIZ_AUTH_TOKEN

    def verify_webhook_signature(self, payload: bytes, headers: dict, secret: str = "") -> bool:
        """
        Documented no-op — same as McubeAdapter. Vobiz's own X-Vobiz-Signature
        HMAC is computed over the request URL (not the body), which doesn't
        fit this interface's (payload, headers) shape. Authentication instead
        relies on an unguessable per-tenant secret in the webhook URL path
        itself, checked with secrets.compare_digest in webhooks_vobiz.py —
        same convention Mcube already uses for the same reason.
        """
        return True

    def parse_call_webhook(self, payload: dict) -> CallWebhookPayload:
        """
        Expects the merged payload from webhooks_vobiz.py:
        {
            "CallUUID": "...", "From": "+91...", "To": "+91...",
            "Direction": "inbound", "RecordUrl": "https://api.vobiz.ai/...",
            "RecordingDuration": "42", "agent_number": "+91...",
            "started_at": "...", "ended_at": "...",
            "ivr_dial_status": "completed",  # from the Dial callbackUrl webhook, or "" if it never fired
        }
        """
        return CallWebhookPayload(
            ivr_call_id=payload.get("CallUUID", ""),
            direction=(payload.get("Direction") or "inbound").lower(),
            from_number=self._normalize_phone(payload.get("From", "")),
            to_number=self._normalize_phone(payload.get("To", "")),
            duration_seconds=self._parse_int(payload.get("RecordingDuration")),
            recording_url=payload.get("RecordUrl") or payload.get("RecordFile") or "",
            agent_number=self._normalize_phone(payload.get("agent_number", "")),
            started_at=payload.get("started_at", ""),
            ended_at=payload.get("ended_at", ""),
            provider="vobiz",
            raw=payload,
            ivr_dial_status=payload.get("ivr_dial_status", ""),
        )

    async def initiate_click_to_call(
        self,
        agent_number: str,
        guest_number: str,
        *,
        did_number: str = "",
        answer_url: str = "",
    ) -> str:
        """
        Fires Vobiz's REST Call API (POST .../Account/{auth_id}/Call/, Basic
        auth with auth_id/auth_token — confirmed against vobiz.ai/docs/
        quick-start). This dials `agent_number` (leg A) first; `answer_url`
        is a HAIP webhook that fires once the agent picks up and returns XML
        dialing the guest as leg B (see webhooks_vobiz.py's
        outbound-answer endpoint) — Vobiz has no single "bridge two numbers"
        call primitive, only sequential-leg dialing driven by AnswerURL XML,
        same pattern as the inbound flow's Answer→Dial cycle.

        did_number/answer_url are keyword-only and required here (unlike
        the shared IVRAdapter signature) because, unlike CallerDesk/Acefone/
        Mcube's single shared HAIP account, every field this call needs is
        per-tenant — the caller (calls.py's click-to-call endpoint) is the
        only place that has that context.
        """
        if not did_number or not answer_url:
            raise ValueError("Vobiz click-to-call requires did_number and answer_url")
        if not self.auth_id or not self.auth_token:
            raise ValueError("Vobiz auth_id/auth_token not configured for this tenant")

        url = f"https://api.vobiz.ai/api/v1/Account/{self.auth_id}/Call/"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                auth=(self.auth_id, self.auth_token),
                data={"from": did_number, "to": agent_number, "answer_url": answer_url},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()

        # Response field name for the call UUID isn't confirmed from docs
        # (same situation as the recording-callback payload — see
        # webhooks_vobiz.py's vobiz_recording_raw_payload log) — try the
        # likely candidates and fail loudly rather than silently returning "".
        call_id = (
            body.get("request_uuid")
            or body.get("call_uuid")
            or body.get("RequestUUID")
            or body.get("CallUUID")
            or ""
        )
        if not call_id:
            raise ValueError(f"Vobiz Call API returned no recognizable call id: {body!r}")
        return call_id

    async def fetch_recording(self, recording_url: str) -> bytes:
        """Download the recording from Vobiz's Recordings API. Requires the
        same X-Auth-ID/X-Auth-Token account credentials as every other Vobiz
        API call — the RecordUrl is not a public presigned link."""
        parsed = urlparse(recording_url)
        if parsed.scheme != "https" or parsed.netloc not in _ALLOWED_RECORDING_HOSTS:
            raise ValueError(
                f"Recording URL rejected (scheme={parsed.scheme!r}, host={parsed.netloc!r}). "
                "Only HTTPS from api.vobiz.ai is permitted."
            )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                recording_url,
                timeout=60,
                headers={
                    "X-Auth-ID": self.auth_id,
                    "X-Auth-Token": self.auth_token,
                },
            )
            resp.raise_for_status()
            return resp.content

    @staticmethod
    def verify_vobiz_signature(url: str, headers: dict, auth_token: str) -> bool:
        """
        Vobiz's own V3/V2 HMAC-SHA256 callback signature, per their docs.
        Not used for authorization (see verify_webhook_signature docstring)
        but kept available to double-check a payload really came from Vobiz
        if ever needed, without changing the auth model.
        """
        normalized = {k.lower(): v for k, v in headers.items()}
        signature = normalized.get("x-vobiz-signature-v3") or ""
        nonce = normalized.get("x-vobiz-signature-v3-nonce") or ""
        version = "v3"
        if not signature:
            signature = normalized.get("x-vobiz-signature-v2") or ""
            nonce = normalized.get("x-vobiz-signature-v2-nonce") or ""
            version = "v2"
        if not signature or not nonce or not auth_token:
            return False

        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        signed_payload = base_url + (f".{nonce}" if version == "v3" else nonce)
        expected = base64.b64encode(
            hmac.new(auth_token.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii")
        return hmac.compare_digest(expected, signature)

    def _normalize_phone(self, phone: str) -> str:
        if not phone:
            return ""
        phone = phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+91" + phone.lstrip("0")
        return phone

    @staticmethod
    def _parse_int(raw) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
