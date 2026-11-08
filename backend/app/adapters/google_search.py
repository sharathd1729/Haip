"""Google Search Console + PageSpeed Insights (official APIs only, hosts pinned).

Search Console (docs read 8 Nov 2026, developers.google.com/webmaster-tools/v1): OAuth scope
https://www.googleapis.com/auth/webmasters (read + sitemap submit; the read-only scope cannot submit a sitemap).
  GET  https://searchconsole.googleapis.com/webmasters/v3/sites                         -> siteEntry[{siteUrl, permissionLevel}]
  POST .../sites/{siteUrl}/searchAnalytics/query  {startDate, endDate, dimensions, rowLimit (<= 25000), startRow}
  PUT  .../sites/{siteUrl}/sitemaps/{feedpath}                                          -> 204
siteUrl is "https://www.example.com/" (URL-prefix property) or "sc-domain:example.com" (domain property), percent-encoded.
Data is about 2-3 days behind and kept 16 months. Token exchange / refresh = adapters.google_business (same endpoint).

PageSpeed Insights v5: GET https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=&strategy=&category=performance
&key= (server API key; never put in a log line or an error message). loadingExperience = CrUX field data for the page
(p75 of real Chrome visitors, last 28 days), originLoadingExperience = the whole site's when the page has too few visits.
"""

from datetime import date
from urllib.parse import quote

import httpx

from app.adapters.google_business import GoogleBusiness
from app.adapters.instagram.publishing import PublishError

SCOPE = "https://www.googleapis.com/auth/webmasters"
GSC = "https://searchconsole.googleapis.com/webmasters/v3/"
PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
MAX_ROW_LIMIT = 25000
PSI_TIMEOUT = 90  # a Lighthouse run takes 10-40 s


def _site(site_url: str) -> str:
    return quote(site_url, safe="")


class SearchConsole(GoogleBusiness):
    """Same request/error handling as the Business Profile client, different pinned hosts."""

    HOSTS = frozenset({"searchconsole.googleapis.com"})

    def sites(self) -> list[dict]:
        return [
            {"site_url": e["siteUrl"], "permission": e.get("permissionLevel")}
            for e in self._req("GET", f"{GSC}sites").get("siteEntry") or []
            if e.get("siteUrl")
        ]

    def query(
        self, site_url: str, start: date, end: date, dimensions: list[str], *, row_limit: int, start_row: int = 0
    ) -> list[dict]:
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "rowLimit": min(row_limit, MAX_ROW_LIMIT),
            "startRow": start_row,
        }
        return self._req("POST", f"{GSC}sites/{_site(site_url)}/searchAnalytics/query", json=body).get("rows") or []

    def submit_sitemap(self, site_url: str, sitemap_url: str) -> None:
        self._req("PUT", f"{GSC}sites/{_site(site_url)}/sitemaps/{_site(sitemap_url)}")


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _field(exp: dict) -> dict:
    m = exp.get("metrics") or {}

    def p75(key):
        return _num((m.get(key) or {}).get("percentile"))

    cls = p75("CUMULATIVE_LAYOUT_SHIFT_SCORE")
    lcp, inp = p75("LARGEST_CONTENTFUL_PAINT_MS"), p75("INTERACTION_TO_NEXT_PAINT")
    return {
        "field_lcp_ms": int(lcp) if lcp is not None else None,
        "field_inp_ms": int(inp) if inp is not None else None,
        "field_cls": round(cls / 100, 3) if cls is not None else None,  # CrUX sends CLS x 100
        "field_category": exp.get("overall_category") if m else None,
    }


def parse_pagespeed(data: dict) -> dict:
    """The fields pagespeed_runs keeps, from one runPagespeed answer."""
    lh = data.get("lighthouseResult") or {}
    audits = lh.get("audits") or {}
    score = _num(((lh.get("categories") or {}).get("performance") or {}).get("score"))

    def audit(key):
        return _num((audits.get(key) or {}).get("numericValue"))

    lcp, tbt, cls = audit("largest-contentful-paint"), audit("total-blocking-time"), audit("cumulative-layout-shift")
    out = {
        "lab_performance": round(score * 100) if score is not None else None,
        "lab_lcp_ms": int(lcp) if lcp is not None else None,
        "lab_tbt_ms": int(tbt) if tbt is not None else None,
        "lab_cls": round(cls, 3) if cls is not None else None,
    }
    page = data.get("loadingExperience") or {}
    origin = data.get("originLoadingExperience") or {}
    use_origin = not page.get("metrics") or bool(page.get("origin_fallback"))
    out.update(_field(origin if use_origin else page))
    out["field_is_origin"] = bool(use_origin and origin.get("metrics"))
    return out


def run_pagespeed(url: str, strategy: str, api_key: str, client: httpx.Client | None = None) -> dict:
    c = client or httpx.Client(timeout=PSI_TIMEOUT, follow_redirects=False)
    try:
        r = c.get(PSI, params={"url": url, "strategy": strategy, "category": "performance", "key": api_key})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise PublishError(f"PageSpeed did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if client is None:
            c.close()
    if r.status_code != 200:
        try:
            msg = ((r.json().get("error") or {}).get("message") or "")[:160]
        except ValueError:
            msg = ""
        raise PublishError(
            f"PageSpeed {r.status_code}: {msg}".replace(api_key, "***"),
            transient=r.status_code == 429 or r.status_code >= 500,
            status=r.status_code,
        )
    return parse_pagespeed(r.json())
