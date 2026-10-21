"""Google Business Profile (agency M3): OAuth, locations, posts and review replies.

Docs read 21 Oct 2026 (developers.google.com/my-business): posts are POST
https://mybusiness.googleapis.com/v4/accounts/{a}/locations/{l}/localPosts with languageCode, summary,
callToAction {actionType BOOK|ORDER|SHOP|LEARN_MORE|SIGN_UP|CALL, url}, media [{mediaFormat PHOTO, sourceUrl}] and
topicType (STANDARD, EVENT, OFFER). Reviews: GET .../locations/{l}/reviews; reply: PUT .../reviews/{id}/reply
{"comment"}. Accounts: mybusinessaccountmanagement v1; locations: mybusinessbusinessinformation v1. OAuth scope
https://www.googleapis.com/auth/business.manage, offline access (refresh token). API access needs Google's approval.
All hosts pinned; timeouts, 429 and 5xx are transient.
"""
from typing import Optional
from urllib.parse import urlencode

import httpx

from app.adapters.instagram.publishing import PublishError

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/business.manage"
V4 = "https://mybusiness.googleapis.com/v4/"
ACCOUNTS = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1/"
_HOSTS = {"oauth2.googleapis.com", "mybusiness.googleapis.com", "mybusinessaccountmanagement.googleapis.com",
          "mybusinessbusinessinformation.googleapis.com"}
TIMEOUT = 30
SUMMARY_MAX = 1500
STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTH + "?" + urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                                   "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state})


def _post_form(url: str, form: dict, client: Optional[httpx.Client]) -> dict:
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        r = c.post(url, data=form)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise PublishError(f"Google did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if client is None:
            c.close()
    if r.status_code != 200:
        raise PublishError(f"Google token {r.status_code}: {r.text[:200]}", transient=r.status_code == 429 or r.status_code >= 500)
    return r.json()


def exchange_code(client_id: str, secret: str, code: str, redirect_uri: str, client: Optional[httpx.Client] = None) -> dict:
    return _post_form(TOKEN, {"code": code, "client_id": client_id, "client_secret": secret, "redirect_uri": redirect_uri,
                              "grant_type": "authorization_code"}, client)


def refresh(client_id: str, secret: str, refresh_token: str, client: Optional[httpx.Client] = None) -> dict:
    return _post_form(TOKEN, {"refresh_token": refresh_token, "client_id": client_id, "client_secret": secret,
                              "grant_type": "refresh_token"}, client)


class GoogleBusiness:
    def __init__(self, access_token: str, client: Optional[httpx.Client] = None):
        self._h = {"Authorization": f"Bearer {access_token}"}
        self.c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        self._own = client is None

    def close(self) -> None:
        if self._own:
            self.c.close()

    def _req(self, method: str, url: str, **kw) -> dict:
        if httpx.URL(url).host not in _HOSTS:
            raise PublishError("refusing to call an unexpected host", transient=False)
        try:
            r = self.c.request(method, url, headers=self._h, **kw)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise PublishError(f"Google did not answer: {type(exc).__name__}", transient=True) from exc
        if r.status_code >= 400:
            raise PublishError(f"Google {r.status_code}: {r.text[:300]}", transient=r.status_code == 429 or r.status_code >= 500)
        return r.json() if r.content else {}

    def locations(self) -> list[dict]:
        out = []
        for acct in self._req("GET", ACCOUNTS).get("accounts") or []:
            data = self._req("GET", f"{INFO}{acct['name']}/locations", params={"readMask": "name,title", "pageSize": 100})
            out += [{"account": acct["name"], "location": loc["name"], "title": loc.get("title")}
                    for loc in data.get("locations") or []]
        return out

    def create_post(self, account: str, location: str, summary: str, image_url: Optional[str],
                    action: Optional[dict]) -> dict:
        """account = "accounts/123", location = "locations/456". Returns {name, searchUrl}."""
        body: dict = {"languageCode": "en", "summary": summary[:SUMMARY_MAX], "topicType": "STANDARD"}
        if image_url:
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": image_url}]
        if action:
            body["callToAction"] = action
        return self._req("POST", f"{V4}{account}/{location}/localPosts", json=body)

    def reviews(self, account: str, location: str, page_token: Optional[str] = None) -> dict:
        params = {"pageSize": 50, **({"pageToken": page_token} if page_token else {})}
        return self._req("GET", f"{V4}{account}/{location}/reviews", params=params)

    def reply(self, account: str, location: str, review_id: str, comment: str) -> dict:
        return self._req("PUT", f"{V4}{account}/{location}/reviews/{review_id}/reply", json={"comment": comment[:4000]})
