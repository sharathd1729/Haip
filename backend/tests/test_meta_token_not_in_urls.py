"""Meta access tokens never travel in a URL, an error message or a log line.

httpx puts the full request URL in its error messages, and those reach logs and rows shown on screen, so every
Graph call sends the token in the Authorization header. debug_token keeps `input_token` in the query by Meta's
design: there only the caller's access token moves to the header, and nothing echoes the URL.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from structlog.testing import capture_logs

from app.adapters.marketing import meta_ads, meta_business
from app.adapters.meta_http import safe_error, strip_token
from app.adapters.research import feeds
from app.services import marketing_meta_token, meta_token_expiry, wa_health_service, wa_template_service

TOKEN = "EAAsecret" + "z" * 40
META_ERROR = {"error": {"message": "Invalid parameter", "code": 100}}


def _graph(monkeypatch, module, answer=None, status=400):
    """Point `module.httpx.get/post` at a fake Graph that records every request it receives."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        body = answer(req) if callable(answer) else answer
        return httpx.Response(status, json=body if body is not None else META_ERROR)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    def call(method):
        def fn(url, **kw):
            kw.pop("timeout", None)
            return client.request(method, url, **kw)

        return fn

    monkeypatch.setattr(module.httpx, "get", call("GET"))
    monkeypatch.setattr(module.httpx, "post", call("POST"))
    return seen


def _no_token_in_urls(seen, *, allow_input_token=False):
    assert seen
    for req in seen:
        url = str(req.url)
        if allow_input_token:
            assert req.url.params.get("input_token") == TOKEN and "access_token" not in req.url.params
        else:
            assert TOKEN not in url
        assert req.headers.get("authorization", "").endswith(TOKEN)


def test_strip_token_and_safe_error():
    url = f"https://graph.facebook.com/v20.0/act_1/insights?after=abc&access_token={TOKEN}&limit=5"
    assert strip_token(url) == "https://graph.facebook.com/v20.0/act_1/insights?after=abc&limit=5"
    req = httpx.Request("GET", f"https://graph.facebook.com/x?access_token={TOKEN}")
    exc = httpx.HTTPStatusError(
        f"boom {req.url}", request=req, response=httpx.Response(400, json=META_ERROR, request=req)
    )
    assert TOKEN not in safe_error(exc) and "code 100" in safe_error(exc)
    assert safe_error(httpx.ConnectError(f"no route to {req.url}")) == "ConnectError"


def test_meta_ads_header_only_and_paging_next_loses_its_token(monkeypatch):
    nxt = f"https://graph.facebook.com/v20.0/act_1/insights?after=2&access_token={TOKEN}"
    pages = iter([{"data": [], "paging": {"next": nxt}}, {"data": []}])
    seen = _graph(monkeypatch, meta_ads, answer=lambda req: next(pages), status=200)
    list(meta_ads.fetch_insights(TOKEN, "1", date(2026, 11, 1), date(2026, 11, 2)))
    assert len(seen) == 2 and seen[1].url.params["after"] == "2"
    _no_token_in_urls(seen)

    seen = _graph(monkeypatch, meta_ads)
    with pytest.raises(meta_ads.MetaAdsError) as err:
        meta_ads.list_ad_accounts(TOKEN)
    assert TOKEN not in str(err.value) and err.value.status == 400
    _no_token_in_urls(seen)


def test_meta_business_header_only(monkeypatch):
    seen = _graph(monkeypatch, meta_ads)
    with pytest.raises(meta_ads.MetaAdsError) as err:
        meta_business.inspect_token(TOKEN)
    assert TOKEN not in str(err.value)
    with pytest.raises(meta_ads.MetaAdsError):
        meta_business.list_lead_forms(TOKEN, "147")
    _no_token_in_urls(seen)


def test_research_feeds_instagram_header_only():
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        return httpx.Response(400, json=META_ERROR)

    with pytest.raises(feeds.FeedError) as err:
        feeds.hashtag_top_media(TOKEN, "178", "#goa", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert TOKEN not in str(err.value)
    _no_token_in_urls(seen)


def test_wa_health_header_only(monkeypatch):
    seen = _graph(monkeypatch, wa_health_service)
    data, err = wa_health_service._meta_get("pn1", TOKEN, {"fields": "verified_name"})
    assert data is None and TOKEN not in err and "Invalid parameter" in err
    _no_token_in_urls(seen)


def test_wa_template_debug_token_and_upload(monkeypatch):
    monkeypatch.setattr(wa_template_service.settings, "META_APP_ID", "")
    seen = _graph(monkeypatch, wa_template_service, answer={})
    with pytest.raises(wa_template_service.TemplateError) as err:
        wa_template_service._app_id(TOKEN)
    assert TOKEN not in str(err.value)
    _no_token_in_urls(seen, allow_input_token=True)

    monkeypatch.setattr(wa_template_service.settings, "META_APP_ID", "app1")

    def refused(url, **kw):
        assert TOKEN not in url and "access_token" not in (kw.get("params") or {})
        raise httpx.ConnectError(f"could not reach {url}?access_token={TOKEN}")

    monkeypatch.setattr(wa_template_service.httpx, "post", refused)
    with capture_logs() as logs, pytest.raises(wa_template_service.TemplateError) as err:
        wa_template_service.upload_sample_to_meta(TOKEN, b"%PDF-1.4", "application/pdf", "x.pdf")
    assert TOKEN not in str(err.value) and TOKEN not in repr(logs)


def test_meta_token_expiry_debug_token(monkeypatch):
    seen = _graph(monkeypatch, meta_token_expiry, answer={"data": {"is_valid": True, "expires_at": 0}}, status=200)
    assert meta_token_expiry.fetch_expiry(TOKEN) == {"valid": True, "expires_at": 0}
    _no_token_in_urls(seen, allow_input_token=True)

    def broken(url, **kw):
        raise httpx.ConnectError(f"could not reach {url}?input_token={TOKEN}")

    monkeypatch.setattr(meta_token_expiry.httpx, "get", broken)
    with capture_logs() as logs:
        assert meta_token_expiry.fetch_expiry(TOKEN) is None
    assert logs and TOKEN not in repr(logs)


def test_marketing_meta_token_debug_token():
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        return httpx.Response(400, json=META_ERROR)

    with pytest.raises(marketing_meta_token.MarketingError) as err:
        marketing_meta_token.connect(None, "t1", TOKEN, "u1", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert TOKEN not in str(err.value) and TOKEN not in repr(err.value.__dict__)
    _no_token_in_urls(seen, allow_input_token=True)
