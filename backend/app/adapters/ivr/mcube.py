import httpx
from urllib.parse import urlparse
from app.adapters.ivr.base import IVRAdapter, CallWebhookPayload
from app.core.config import settings

# Only fetch recordings from known Mcube hosts over HTTPS.
# s3.ap-south-1.amazonaws.com is a GENERIC AWS S3 regional endpoint, not a
# Mcube-branded domain -- allowlisting the host alone would trust arbitrary
# S3 buckets. Scope it to Mcube's own bucket path ("app.mcube.com", per the
# path-style URL in their inbound webhook doc: .../app.mcube.com/recordings/...).
_ALLOWED_RECORDING_HOSTS = frozenset({
    "s3.ap-south-1.amazonaws.com",
    "mcube.vmctechnologies.com",  # seen on an outbound-callback recording sample
    "recordings.mcube.com",       # Ratha's actual live inbound recording host --
                                   # every recording was being permanently rejected
                                   # (retried 3x then given up) because this wasn't
                                   # in the allowlist. Confirmed live in production.
})
_S3_BUCKET_PATH_PREFIX = "/app.mcube.com/"


class McubeAdapter(IVRAdapter):
    """Mcube IVR adapter for Ratha (replacing CallerDesk)."""

    OUTBOUND_URL = "https://mcube.vmc.in/api/outboundcall"

    def verify_webhook_signature(self, payload: bytes, headers: dict, secret: str = "") -> bool:
        """
        Mcube's API docs (Inbound/Outbound) document no request-signing or
        shared-secret scheme -- unlike CallerDesk (HMAC) and Acefone.
        Authentication instead happens one layer up, in
        webhooks_mcube.py, via an unguessable per-tenant secret embedded
        in the webhook URL path itself (checked with secrets.compare_digest
        before this adapter is ever invoked). This method is a documented
        no-op kept only for IVRAdapter interface compliance.
        """
        return True

    def parse_call_webhook(self, payload: dict) -> CallWebhookPayload:
        """
        Mcube inbound call-event webhook shape (On Call / On Hangup):
        {
            "starttime": "2023-10-12 11:49:57",
            "callid": "80889767291697091597",
            "callto": "8767316316",
            "landingnumber": "8035053336",
            "callfrom": "7816999444",
            "dialstatus": "ANSWER",
            "filename": "https://s3.ap-south-1.amazonaws.com/app.mcube.com/recordings/...",
            "calltype": "inbound",
            "endtime": "2023-10-12 11:50:28",
            "duration": "00:00:04",
            "gid": "Integration",
            "agentname": "Test"
        }

        Two format quirks vs. CallerDesk/Acefone:
        - "duration" is HH:MM:SS text, not integer seconds.
        - dialstatus (not duration) is the authoritative connected signal;
          duration naturally parses to 0 for anything but ANSWER, so
          call_ingest.py's `answered = duration_seconds > 0` still holds.
        """
        return CallWebhookPayload(
            ivr_call_id=payload.get("callid", ""),
            direction="inbound",
            from_number=self._normalize_phone(payload.get("callfrom", "")),
            to_number=self._normalize_phone(payload.get("landingnumber", "")),
            duration_seconds=self._parse_hms_duration(payload.get("duration", "")),
            recording_url=payload.get("filename", ""),
            agent_number=self._normalize_phone(payload.get("callto", "")),
            started_at=payload.get("starttime", ""),
            ended_at=payload.get("endtime", ""),
            provider="mcube",
            raw=payload,
        )

    async def initiate_click_to_call(self, agent_number: str, guest_number: str) -> str:
        """
        GET Mcube's Outbound API. Implemented per the IVRAdapter contract
        but not wired to any endpoint -- outbound click-to-call is out of
        scope for this pass (matches CallerDesk/Acefone, whose equivalent
        methods are also implemented but unused today).
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self.OUTBOUND_URL,
                params={
                    "apikey": settings.MCUBE_API_KEY,
                    "exenumber": agent_number,
                    "custnumber": guest_number,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            return data.get("callid", "")

    async def fetch_recording(self, recording_url: str) -> bytes:
        """Download recording. Only HTTPS from known Mcube hosts is allowed;
        the shared S3 endpoint is additionally scoped to Mcube's own bucket path."""
        parsed = urlparse(recording_url)
        if parsed.scheme != "https" or parsed.netloc not in _ALLOWED_RECORDING_HOSTS:
            raise ValueError(
                f"Recording URL rejected (scheme={parsed.scheme!r}, host={parsed.netloc!r}). "
                "Only HTTPS from known Mcube domains is permitted."
            )
        if parsed.netloc == "s3.ap-south-1.amazonaws.com" and not parsed.path.startswith(_S3_BUCKET_PATH_PREFIX):
            raise ValueError(
                f"Recording URL rejected: shared S3 host must be scoped to {_S3_BUCKET_PATH_PREFIX!r} "
                f"(got path={parsed.path!r})."
            )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                recording_url,
                timeout=60,
                follow_redirects=False,
                # Mcube's Apache server 404s requests with no/non-browser
                # User-Agent (confirmed live: curl's default UA -> 404,
                # a browser-style UA -> 200). httpx sends no UA by default.
                headers={"User-Agent": "Mozilla/5.0 (compatible; HAIP-RecordingFetcher/1.0)"},
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

    @staticmethod
    def _parse_hms_duration(raw: str) -> int:
        """Parse Mcube's "HH:MM:SS" duration text into total seconds.
        Returns 0 for empty/malformed input (e.g. unanswered calls)."""
        if not raw:
            return 0
        parts = raw.strip().split(":")
        try:
            parts = [int(p) for p in parts]
        except ValueError:
            return 0
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, s = parts[-3:]
        return h * 3600 + m * 60 + s
