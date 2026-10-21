"""Canva Connect API (agency M2b): fill a workspace's own Canva brand template with a draft's text and photo, then
export it as a JPEG for the library. Docs read 21 Oct 2026 (canva.dev/docs/connect):

  * OAuth 2.0 authorization code + PKCE (S256). Authorize: https://www.canva.com/api/oauth/authorize; token:
    POST https://api.canva.com/rest/v1/oauth/token (form body, client id:secret as HTTP Basic). Refresh tokens are
    SINGLE USE: every refresh returns a new one, which the caller must store before using the access token.
  * Autofill + brand templates need the user on Canva Pro, Teams or Enterprise (and MFA on their Canva account).
  * Brand templates: GET /brand-templates, GET /brand-templates/{id}/dataset; assets: POST /asset-uploads (binary body,
    Asset-Upload-Metadata header) then GET /asset-uploads/{job}; autofill: POST /autofills then GET /autofills/{job};
    export: POST /exports then GET /exports/{job}. Export URLs expire after 24 hours; HAIP copies the file at once.
Every host is pinned (api.canva.com for calls, *.canva.com for export downloads). Timeouts, 429 and 5xx are transient.
"""
import base64
import hashlib
import json
import secrets
import time
from typing import Callable, Optional
from urllib.parse import urlencode

import httpx

API = "https://api.canva.com/rest/v1"
AUTHORIZE = "https://www.canva.com/api/oauth/authorize"
SCOPES = ("design:content:read design:content:write design:meta:read brandtemplate:meta:read brandtemplate:content:read "
          "asset:read asset:write")
TIMEOUT = 30
POLL_SECONDS = (1, 2, 3, 5, 8, 8, 8, 8, 8, 8)       # about a minute in all
MAX_EXPORT_BYTES = 25 * 1024 * 1024


class CanvaError(Exception):
    def __init__(self, message: str, *, transient: bool, status: Optional[int] = None):
        super().__init__(message)
        self.transient, self.status = transient, status


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge)."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTHORIZE + "?" + urlencode({"code_challenge": challenge, "code_challenge_method": "S256", "scope": SCOPES,
                                        "response_type": "code", "client_id": client_id, "state": state,
                                        "redirect_uri": redirect_uri})


def _token(client_id: str, client_secret: str, form: dict, client: Optional[httpx.Client] = None) -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        r = c.post(f"{API}/oauth/token", data=form, headers={"Authorization": f"Basic {basic}"})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise CanvaError(f"Canva did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if client is None:
            c.close()
    if r.status_code != 200:
        raise CanvaError(f"Canva token {r.status_code}: {r.text[:200]}", transient=r.status_code == 429 or r.status_code >= 500,
                         status=r.status_code)
    data = r.json()
    if not data.get("access_token") or not data.get("refresh_token"):
        raise CanvaError("Canva returned no token.", transient=False)
    return data


def exchange_code(client_id: str, client_secret: str, code: str, verifier: str, redirect_uri: str,
                  client: Optional[httpx.Client] = None) -> dict:
    return _token(client_id, client_secret, {"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                             "redirect_uri": redirect_uri}, client)


def refresh(client_id: str, client_secret: str, refresh_token: str, client: Optional[httpx.Client] = None) -> dict:
    return _token(client_id, client_secret, {"grant_type": "refresh_token", "refresh_token": refresh_token}, client)


class Canva:
    def __init__(self, access_token: str, client: Optional[httpx.Client] = None, sleep: Callable[[float], None] = time.sleep):
        self._c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        self._own = client is None
        self._h = {"Authorization": f"Bearer {access_token}"}
        self._sleep = sleep

    def close(self) -> None:
        if self._own:
            self._c.close()

    def _req(self, method: str, path: str, **kw) -> dict:
        url = f"{API}{path}"
        if httpx.URL(url).host != "api.canva.com":
            raise CanvaError("refusing to call an unexpected host", transient=False)
        headers = {**self._h, **kw.pop("headers", {})}
        try:
            r = self._c.request(method, url, headers=headers, **kw)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise CanvaError(f"Canva did not answer: {type(exc).__name__}", transient=True) from exc
        if r.status_code >= 400:
            try:
                msg = (r.json() or {}).get("message") or r.text[:200]
            except ValueError:
                msg = r.text[:200]
            raise CanvaError(f"Canva {r.status_code}: {msg}", transient=r.status_code == 429 or r.status_code >= 500,
                             status=r.status_code)
        return r.json() if r.content else {}

    def _poll(self, path: str) -> dict:
        for wait in POLL_SECONDS:
            job = self._req("GET", path).get("job") or {}
            if job.get("status") == "success":
                return job
            if job.get("status") == "failed":
                err = job.get("error") or {}
                raise CanvaError(f"Canva job failed: {err.get('code')}: {err.get('message')}", transient=False)
            self._sleep(wait)
        raise CanvaError("Canva is still working on it; try again shortly.", transient=True)

    def brand_templates(self, query: Optional[str] = None) -> list[dict]:
        params = {"dataset": "non_empty", **({"query": query} if query else {})}
        out, cont = [], None
        for _ in range(5):
            data = self._req("GET", "/brand-templates", params={**params, **({"continuation": cont} if cont else {})})
            out += [{"id": t["id"], "title": t.get("title"), "thumbnail": (t.get("thumbnail") or {}).get("url"),
                     "view_url": t.get("view_url")} for t in data.get("items") or []]
            cont = data.get("continuation")
            if not cont:
                break
        return out

    def dataset(self, template_id: str) -> dict[str, str]:
        """field name -> "text" | "image" | "chart"."""
        data = self._req("GET", f"/brand-templates/{template_id}/dataset")
        return {k: (v or {}).get("type") for k, v in (data.get("dataset") or {}).items()}

    def upload_asset(self, content: bytes, name: str) -> str:
        meta = json.dumps({"name_base64": base64.b64encode(name[:50].encode()).decode()})
        job = self._req("POST", "/asset-uploads", content=content,
                        headers={"Content-Type": "application/octet-stream", "Asset-Upload-Metadata": meta}).get("job") or {}
        if job.get("status") != "success":
            job = self._poll(f"/asset-uploads/{job.get('id')}")
        return (job.get("asset") or {})["id"]

    def autofill(self, template_id: str, data: dict, title: str) -> dict:
        job = self._req("POST", "/autofills", json={"brand_template_id": template_id, "title": title[:255], "data": data}).get("job") or {}
        if job.get("status") != "success":
            job = self._poll(f"/autofills/{job.get('id')}")
        design = ((job.get("result") or {}).get("design")) or {}
        if not design.get("id") and not design.get("url"):
            raise CanvaError("Canva made no design.", transient=False)
        return {"id": design.get("id"), "url": design.get("url"), "thumbnail": (design.get("thumbnail") or {}).get("url")}

    def export_jpg(self, design_id: str) -> list[str]:
        job = self._req("POST", "/exports", json={"design_id": design_id, "format": {"type": "jpg", "quality": 90}}).get("job") or {}
        if job.get("status") != "success":
            job = self._poll(f"/exports/{job.get('id')}")
        return list(job.get("urls") or [])

    def download(self, url: str) -> bytes:
        host = httpx.URL(url).host or ""
        if httpx.URL(url).scheme != "https" or not (host == "canva.com" or host.endswith(".canva.com")):
            raise CanvaError("refusing to download from an unexpected host", transient=False)
        try:
            r = self._c.get(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise CanvaError(f"Download failed: {type(exc).__name__}", transient=True) from exc
        if r.status_code != 200 or len(r.content) > MAX_EXPORT_BYTES:
            raise CanvaError(f"Download failed ({r.status_code})", transient=r.status_code >= 500)
        return r.content
