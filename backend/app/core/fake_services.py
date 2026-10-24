"""Local test mode (EXTERNAL_SERVICES=fake, docs/LOCAL_TESTING.md).

Every outbound HTTP call except the AI providers and localhost is answered here instead of leaving the machine:
WhatsApp, Instagram, Meta Graph/ads, Razorpay, Resend, IVR click-to-call, the personal-WhatsApp bridge, web push and
anything added later. The call is appended to an outbox file (what WOULD have been sent, to whom) and a realistic
success payload is returned. boto3 S3 (Cloudflare R2 / AWS) is swapped for a folder on disk.

It works by patching httpx's transports, requests' HTTPAdapter and boto3.client once per process (API, Celery worker,
scripts), so no adapter needs its own fake. It refuses to run in production, and Settings refuses EXTERNAL_SERVICES=fake
there too, so production can never load it.
"""
from __future__ import annotations

import html
import io
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import structlog

from app.core.config import settings

log = structlog.get_logger()

# Real calls still go to these: the AI router stays live, and local services (the API itself, Postgres-backed tools).
AI_HOSTS = {
    "integrate.api.nvidia.com", "ai.api.nvidia.com", "api.nvcf.nvidia.com",
    "generativelanguage.googleapis.com",
    "api.sarvam.ai", "api.groq.com", "api.deepgram.com",
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SECRET_PARAMS = {"access_token", "appsecret_proof", "client_secret", "key", "token"}

_installed = False
_lock = threading.Lock()


def enabled() -> bool:
    return settings.EXTERNAL_SERVICES == "fake" and settings.ENVIRONMENT != "production"


def data_dir() -> Path:
    root = Path(settings.LOCAL_DATA_DIR) if settings.LOCAL_DATA_DIR else Path(__file__).resolve().parents[3] / ".local-data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _outbox_file() -> Path:
    return data_dir() / "outbox.jsonl"


def passes_through(host: str) -> bool:
    host = (host or "").lower().strip("[]")
    return host in AI_HOSTS or host in LOCAL_HOSTS or host.endswith(".localhost")


# ── What would have been sent ─────────────────────────────────────────────────────────────────────────────────────────

def _service(host: str, path: str, body: dict) -> str:
    if "facebook.com" in host or "instagram.com" in host:
        if body.get("messaging_product") == "whatsapp" or "/message_templates" in path:
            return "whatsapp"
        if path.endswith("/messages") or "instagram" in host or "/media" in path:
            return "instagram"
        return "meta"
    for key, name in (("razorpay", "razorpay"), ("resend", "email"), ("vobiz", "ivr"), ("acefone", "ivr"),
                      ("callerdesk", "ivr"), ("mcube", "ivr"), ("whatsapp-bridge", "whatsapp_personal"),
                      ("push", "web_push"), ("fcm.googleapis", "web_push"), ("mozilla", "web_push"),
                      ("windows.com", "web_push"), ("apple.com", "web_push")):
        if key in host:
            return name
    return "other"


def _recipient_and_text(service: str, body: dict) -> tuple[str, str]:
    if service == "whatsapp":
        kind = body.get("type")
        text = (body.get("text") or {}).get("body") or ""
        if kind == "template":
            text = f"[template] {(body.get('template') or {}).get('name', '')}"
        elif kind and kind != "text":
            text = text or f"[{kind}] {json.dumps(body.get(kind) or {})[:200]}"
        return str(body.get("to", "")), text
    if service == "instagram":
        rid = (body.get("recipient") or {}).get("id") if isinstance(body.get("recipient"), dict) else body.get("recipient")
        msg = body.get("message") or {}
        if isinstance(msg, str):
            try:
                msg = json.loads(msg)
            except ValueError:
                msg = {"text": msg}
        return str(rid or ""), msg.get("text") or body.get("caption") or ""
    if service == "email":
        to = body.get("to")
        return ", ".join(to) if isinstance(to, list) else str(to or ""), str(body.get("subject") or "")
    if service == "razorpay":
        customer = body.get("customer") or {}
        amount = body.get("amount")
        text = f"Payment link INR {amount / 100:,.2f} - {body.get('description', '')}" if isinstance(amount, (int, float)) else ""
        return str(customer.get("contact") or customer.get("email") or ""), text
    if service == "ivr":
        return str(body.get("to") or body.get("destination_number") or ""), "click-to-call"
    return "", ""


def _parse_body(content: bytes, content_type: str) -> dict:
    if not content:
        return {}
    if "json" in content_type or content[:1] in (b"{", b"["):
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {"items": parsed}
        except ValueError:
            pass
    if "form-urlencoded" in content_type:
        return dict(parse_qsl(content.decode("utf-8", "replace")))
    return {"_raw": f"<{len(content)} bytes {content_type or 'unknown'}>"}


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    query = "&".join(f"{k}={'***' if k in _SECRET_PARAMS else v}" for k, v in parse_qsl(parts.query))
    return f"{parts.scheme}://{parts.netloc}{parts.path}" + (f"?{query}" if query else "")


def record(method: str, url: str, content: bytes, content_type: str) -> tuple[str, dict]:
    """Append one intercepted call to the outbox and return (service, fake response body)."""
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), parts.path
    body = _parse_body(content, content_type)
    query = dict(parse_qsl(parts.query))
    service = _service(host, path, body)
    to, text = _recipient_and_text(service, body)
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "service": service, "method": method, "url": _safe_url(url), "to": to, "text": text[:1000],
        "body": json.dumps(body, default=str)[:4000],
    }
    with _lock, _outbox_file().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.info("fake_external_call", service=service, method=method, host=host, path=path)
    return service, fake_payload(method, host, path, body, query)


def fake_payload(method: str, host: str, path: str, body: dict, query: dict) -> dict:
    fid = uuid.uuid4().hex[:16]
    if "facebook.com" in host or "instagram.com" in host:
        if path.endswith("/messages") and body.get("messaging_product") == "whatsapp":
            to = str(body.get("to", ""))
            return {"messaging_product": "whatsapp", "contacts": [{"input": to, "wa_id": to.lstrip("+")}],
                    "messages": [{"id": f"wamid.FAKE{fid}"}]}
        if path.endswith("/messages"):
            rid = (body.get("recipient") or {}).get("id", "") if isinstance(body.get("recipient"), dict) else ""
            return {"recipient_id": rid, "message_id": f"mid.FAKE{fid}"}
        if method == "GET" and "status_code" in query.get("fields", ""):
            return {"id": path.strip("/").split("/")[-1], "status_code": "FINISHED"}
        if method == "GET":
            return {"id": path.strip("/").split("/")[-1] or fid, "data": [], "paging": {}}
        return {"id": f"FAKE{fid}", "success": True}
    if "razorpay" in host:
        if path.rstrip("/").endswith("/payment_links") and method == "POST":
            return {"id": f"plink_FAKE{fid}", "short_url": f"{_api_base()}/dev/outbox#plink_FAKE{fid}",
                    "status": "created", "amount": body.get("amount"), "amount_paid": 0, "currency": "INR",
                    "reference_id": body.get("reference_id"), "payments": [], "created_at": int(datetime.now().timestamp())}
        if path.rstrip("/").endswith("/payment_links"):
            return {"count": 0, "items": []}
        if path.endswith("/cancel"):
            return {"id": path.split("/")[-2], "status": "cancelled"}
        return {"id": path.rstrip("/").split("/")[-1], "status": "created", "amount_paid": 0, "payments": []}
    if "resend" in host:
        return {"id": f"fake-email-{fid}"}
    # IVR click-to-call, bridge, push and anything new: a superset of the success fields our adapters read.
    return {"id": f"FAKE{fid}", "success": True, "status": "ok", "message": "faked locally", "data": [],
            "request_uuid": f"fake-{fid}", "call_uuid": f"fake-{fid}", "message_id": f"fake-{fid}"}


def _api_base() -> str:
    return (settings.API_BASE_URL or "http://localhost:8000").rstrip("/")


def read_outbox(limit: int = 200) -> list[dict]:
    path = _outbox_file()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in reversed(lines) if line.strip()]


# ── Local object storage (stands in for R2 / S3) ──────────────────────────────────────────────────────────────────────

class LocalS3:
    """The few boto3 S3 calls HAIP makes, against <data dir>/s3/<key>. Presigned URLs point at /dev/media/<key>."""

    def __init__(self):
        self.root = (data_dir() / "s3").resolve()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError(f"key outside local store: {key!r}")
        return p

    def put_object(self, Bucket=None, Key="", Body=b"", ContentType=None, **_):
        p = self._path(Key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(Body.read() if hasattr(Body, "read") else (Body.encode() if isinstance(Body, str) else Body))
        return {"ETag": uuid.uuid4().hex}

    def get_object(self, Bucket=None, Key="", **_):
        data = self._path(Key).read_bytes()  # FileNotFoundError, like a NoSuchKey
        return {"Body": io.BytesIO(data), "ContentLength": len(data)}

    def head_object(self, Bucket=None, Key="", **_):
        return {"ContentLength": self._path(Key).stat().st_size}

    def delete_object(self, Bucket=None, Key="", **_):
        self._path(Key).unlink(missing_ok=True)
        return {}

    def delete_objects(self, Bucket=None, Delete=None, **_):
        for obj in (Delete or {}).get("Objects", []):
            self.delete_object(Key=obj["Key"])
        return {"Deleted": (Delete or {}).get("Objects", [])}

    def generate_presigned_url(self, ClientMethod="get_object", Params=None, ExpiresIn=3600, **_):
        return f"{_api_base()}/dev/media/{(Params or {}).get('Key', '')}"


# ── Patching ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def install() -> None:
    """Patch httpx, requests and boto3 for this process. Idempotent."""
    global _installed
    if settings.ENVIRONMENT == "production":
        raise RuntimeError("EXTERNAL_SERVICES=fake is never allowed in production")
    if _installed:
        return
    import boto3
    import httpx

    real_sync = httpx.HTTPTransport.handle_request
    real_async = httpx.AsyncHTTPTransport.handle_async_request

    def _fake(request: httpx.Request, content: bytes) -> httpx.Response:
        _, payload = record(request.method, str(request.url), content, request.headers.get("content-type", ""))
        return httpx.Response(200, json=payload, request=request)

    def handle_request(self, request):
        if passes_through(request.url.host):
            return real_sync(self, request)
        return _fake(request, request.read())

    async def handle_async_request(self, request):
        if passes_through(request.url.host):
            return await real_async(self, request)
        return _fake(request, await request.aread())

    httpx.HTTPTransport.handle_request = handle_request
    httpx.AsyncHTTPTransport.handle_async_request = handle_async_request

    try:
        import requests
        from requests.adapters import HTTPAdapter
        real_send = HTTPAdapter.send

        def send(self, request, *args, **kwargs):
            if passes_through(urlsplit(request.url).hostname or ""):
                return real_send(self, request, *args, **kwargs)
            body = request.body.encode() if isinstance(request.body, str) else (request.body or b"")
            _, payload = record(request.method, request.url, body, request.headers.get("Content-Type", ""))
            resp = requests.Response()
            resp.status_code, resp._content, resp.url, resp.request = 201, json.dumps(payload).encode(), request.url, request
            resp.headers["Content-Type"] = "application/json"
            return resp

        HTTPAdapter.send = send
    except ImportError:
        pass

    real_client = boto3.client

    def client(service_name, *args, **kwargs):
        return LocalS3() if service_name == "s3" else real_client(service_name, *args, **kwargs)

    boto3.client = client
    _installed = True
    log.warning("external_services_faked", outbox=str(_outbox_file()), ai_hosts_live=sorted(AI_HOSTS))


def install_if_enabled() -> None:
    if enabled():
        install()


# ── Dev-only pages (mounted by main.py only when enabled(), so they 404 everywhere else) ─────────────────────────────

def build_router():
    from fastapi import APIRouter, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse

    router = APIRouter(prefix="/dev", include_in_schema=False)

    @router.get("/outbox.json")
    def outbox_json(limit: int = 200):
        return {"items": read_outbox(min(max(limit, 1), 2000))}

    @router.get("/outbox", response_class=HTMLResponse)
    def outbox_page(limit: int = 200, all: bool = False):
        items = [e for e in read_outbox(min(max(limit, 1), 2000)) if all or e.get("method") != "GET"]
        rows = "".join(
            "<tr><td>{at}</td><td><b>{service}</b></td><td>{to}</td><td>{text}</td>"
            "<td><details><summary>{method} {url}</summary><pre>{body}</pre></details></td></tr>".format(
                **{k: html.escape(str(e.get(k, ""))) for k in ("at", "service", "to", "text", "method", "url", "body")})
            for e in items
        ) or '<tr><td colspan="5">Nothing would have been sent yet.</td></tr>'
        return (
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Fake outbox</title><style>body{font:14px system-ui;margin:16px}table{border-collapse:collapse;"
            "width:100%;table-layout:fixed}td,th{border-bottom:1px solid #ddd;padding:6px;vertical-align:top;"
            "text-align:left;overflow-wrap:anywhere}"
            "pre{white-space:pre-wrap;max-width:60ch}</style><h1>Fake outbox (local test mode)</h1>"
            "<p>Nothing on this page left your laptop. Newest first. Refresh to update. Sends only; "
            "<a href='?all=1'>show reads too</a>.</p>"
            "<table><tr><th>When (UTC)</th><th>Service</th><th>To</th><th>Message</th><th>Request</th></tr>"
            f"{rows}</table>"
        )

    @router.get("/media/{key:path}")
    def media(key: str):
        try:
            path = LocalS3()._path(key)
        except ValueError:
            raise HTTPException(404)
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    return router
