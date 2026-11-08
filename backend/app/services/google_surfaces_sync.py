"""Pull what Google reports about the business into HAIP's own tables (official APIs only; nothing is scraped).

  pull_gbp        Business Profile Performance API, every location on the google_business connection. First run
                  backfills GBP_BACKFILL_DAYS (18 months, Google's limit) in GBP_CHUNK_DAYS windows; later runs re-read the
                  last GBP_RECENT_DAYS (Google revises recent days). Upsert per (location, day, metric).
  pull_gsc        Search Console, the chosen property. Totals by date (one call per window) + rows by
                  query x page x country x device, one call per day capped at GSC_ROWS_PER_DAY (Google's order: most
                  clicks first), a day replaced as a whole (idempotent). Recent GSC_RECENT_DAYS every run, then the backfill
                  walks back GSC_BACKFILL_PER_RUN days per run until GSC_HISTORY_DAYS (16 months); the task chains itself
                  while backfill remains. Also submits the sitemap when its URL changed.
  pull_pagespeed  PageSpeed Insights (server key PAGESPEED_API_KEY; none = skipped with a note), home + the most-visited
                  stay pages (PSI_PAGES in all), mobile and desktop, one row per (url, strategy, week).
Failure state per connection in Integration.config["metrics_pull"] = {last_ok_at, last_error, failures, backoff_until}:
a quota (429) or any other failure backs off 2^failures hours (max BACKOFF_MAX_HOURS); integration_health turns the
connection amber after one failure, red after three. Error text never carries a token or key.
"""

import hashlib
from datetime import UTC, date, datetime, timedelta

import httpx
import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.adapters import google_search as gs
from app.adapters.instagram.publishing import PublishError
from app.core.config import settings
from app.models.google_surfaces import GbpDailyMetric, GscDailyTotal, GscSearchRow, PageSpeedRun
from app.models.integration import Integration
from app.services import marketing_channel_connections as conns
from app.services import search_console_connection as gsc_conn

log = structlog.get_logger()

GBP_BACKFILL_DAYS = 540
GBP_CHUNK_DAYS = 90
GBP_RECENT_DAYS = 10
GSC_HISTORY_DAYS = 486
GSC_RECENT_DAYS = 5
GSC_BACKFILL_PER_RUN = 30
GSC_ROWS_PER_DAY = 1000
GSC_DIMENSIONS = ["query", "page", "country", "device"]
PSI_PAGES = 4
PSI_STRATEGIES = ("mobile", "desktop")
BACKOFF_MAX_HOURS = 48
STATE = "metrics_pull"


class Skipped(Exception):
    """Nothing to pull (not connected, backing off, no property)."""


# ── failure state ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _state(integ: Integration) -> dict:
    return dict((integ.config or {}).get(STATE) or {})


def backing_off(integ: Integration, now: datetime | None = None) -> bool:
    until = _state(integ).get("backoff_until")
    return bool(until) and datetime.fromisoformat(until) > (now or datetime.now(UTC))


def record_ok(integ: Integration, **extra) -> None:
    st = {
        **_state(integ),
        "last_ok_at": datetime.now(UTC).isoformat(),
        "failures": 0,
        "last_error": None,
        "backoff_until": None,
        **extra,
    }
    integ.config = {**(integ.config or {}), STATE: st}


def record_failure(integ: Integration, exc: Exception, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    st = _state(integ)
    failures = int(st.get("failures") or 0) + 1
    status = getattr(exc, "status", None)
    reason = (
        "Google's daily limit was reached; HAIP tries again later."
        if status == 429
        else "Google refused access. Reconnect it."
        if status in (401, 403)
        else "Google did not answer. HAIP tries again later."
    )
    st.update(
        failures=failures,
        last_error=reason,
        last_error_at=now.isoformat(),
        backoff_until=(now + timedelta(hours=min(2**failures, BACKOFF_MAX_HOURS))).isoformat(),
    )
    integ.config = {**(integ.config or {}), STATE: st}
    return st


# ── Business Profile ──────────────────────────────────────────────────────────────────────────────────────────────────


def _windows(start: date, end: date, size: int):
    cur = start
    while cur <= end:
        nxt = min(end, cur + timedelta(days=size - 1))
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def _upsert_gbp(db: Session, tenant_id: str, location: str, rows: list[tuple[str, date, int]]) -> int:
    if not rows:
        return 0
    days = [d for _, d, _ in rows]
    have = {
        (r.day, r.metric): r
        for r in db.query(GbpDailyMetric).filter(
            GbpDailyMetric.tenant_id == tenant_id,
            GbpDailyMetric.location == location,
            GbpDailyMetric.day >= min(days),
            GbpDailyMetric.day <= max(days),
        )
    }
    for metric, day, value in rows:
        row = have.get((day, metric))
        if row is None:
            row = GbpDailyMetric(tenant_id=tenant_id, location=location, day=day, metric=metric)
            db.add(row)
            have[(day, metric)] = row
        row.value = value
    db.flush()
    return len(rows)


def pull_gbp(db: Session, tenant_id: str, today: date, *, http: httpx.Client | None = None) -> dict:
    integ = conns.connection(db, tenant_id, conns.GOOGLE_KIND)
    if integ is None or not integ.credentials_kms_blob:
        raise Skipped("not_connected")
    if backing_off(integ):
        raise Skipped("backing_off")
    sp = None
    try:
        client, cfg = conns.google_client(db, tenant_id, http=http)  # may commit a refreshed token first
        sp = db.begin_nested()  # a failure undoes only this pull's rows
        first = not _state(integ).get("backfilled")
        start = today - timedelta(days=GBP_BACKFILL_DAYS if first else GBP_RECENT_DAYS)
        end = today - timedelta(days=1)
        stored, skipped = 0, []
        for loc in cfg.get("locations") or []:
            try:
                for a, b in _windows(start, end, GBP_CHUNK_DAYS):
                    stored += _upsert_gbp(db, tenant_id, loc["location"], client.daily_metrics(loc["location"], a, b))
            except PublishError as exc:
                if exc.transient:
                    raise
                skipped.append(
                    loc.get("title") or loc["location"]
                )  # e.g. an unverified location: the others still count
        sp.commit()
        record_ok(integ, backfilled=True, skipped_locations=skipped)
        return {"stored": stored, "skipped_locations": len(skipped)}
    except PublishError as exc:
        if sp is not None and sp.is_active:
            sp.rollback()
        st = record_failure(integ, exc)
        log.warning("gbp_metrics_pull_failed", tenant_id=tenant_id, status=exc.status, failures=st["failures"])
        return {"failed": True, "status": exc.status}


# ── Search Console ────────────────────────────────────────────────────────────────────────────────────────────────────


def _key(prop: str, day: date, keys: list[str]) -> str:
    return hashlib.sha256("\x1f".join([prop, day.isoformat(), *keys]).encode()).hexdigest()


def _store_totals(db: Session, tenant_id: str, prop: str, rows: list[dict]) -> int:
    parsed = [(date.fromisoformat(r["keys"][0]), r) for r in rows if r.get("keys")]
    if not parsed:
        return 0
    have = {
        t.day: t
        for t in db.query(GscDailyTotal).filter(
            GscDailyTotal.tenant_id == tenant_id,
            GscDailyTotal.property == prop,
            GscDailyTotal.day >= min(d for d, _ in parsed),
            GscDailyTotal.day <= max(d for d, _ in parsed),
        )
    }
    for day, r in parsed:
        t = have.get(day) or GscDailyTotal(tenant_id=tenant_id, property=prop, day=day)
        t.clicks, t.impressions = int(r.get("clicks") or 0), int(r.get("impressions") or 0)
        t.ctr, t.position = r.get("ctr"), r.get("position")
        db.add(t)
    db.flush()
    return len(parsed)


def store_day_rows(db: Session, tenant_id: str, prop: str, day: date, rows: list[dict]) -> int:
    """Replace one day's query rows (idempotent: a re-run gives the same rows, a row Google dropped goes)."""
    db.query(GscSearchRow).filter_by(tenant_id=tenant_id, property=prop, day=day).delete(synchronize_session=False)
    seen = set()
    for r in rows:
        if len(seen) >= GSC_ROWS_PER_DAY:
            break
        keys = [str(k) for k in (r.get("keys") or [])]
        if len(keys) != 4:
            continue
        key = _key(prop, day, keys)
        if key in seen:
            continue
        seen.add(key)
        db.add(
            GscSearchRow(
                tenant_id=tenant_id,
                property=prop,
                day=day,
                query=keys[0][:500],
                page=keys[1][:1000],
                country=keys[2][:3],
                device=keys[3][:10],
                clicks=int(r.get("clicks") or 0),
                impressions=int(r.get("impressions") or 0),
                ctr=r.get("ctr"),
                position=r.get("position"),
                row_key=key,
            )
        )
    db.flush()
    return len(seen)


def _gsc_days(sc: gs.SearchConsole, db: Session, tenant_id: str, prop: str, start: date, end: date) -> int:
    if start > end:
        return 0
    _store_totals(db, tenant_id, prop, sc.query(prop, start, end, ["date"], row_limit=GSC_HISTORY_DAYS + 10))
    n, day = 0, start
    while day <= end:
        n += store_day_rows(
            db, tenant_id, prop, day, sc.query(prop, day, day, GSC_DIMENSIONS, row_limit=GSC_ROWS_PER_DAY)
        )
        day += timedelta(days=1)
    return n


def pull_gsc(db: Session, tenant_id: str, today: date, *, http: httpx.Client | None = None) -> dict:
    """{"stored", "more"}: more = backfill remains (the task queues itself again)."""
    integ = gsc_conn.connection(db, tenant_id)
    if integ is None or not integ.credentials_kms_blob:
        raise Skipped("not_connected")
    prop = (integ.config or {}).get("property")
    if not prop:
        raise Skipped("no_property")
    if backing_off(integ):
        raise Skipped("backing_off")
    sp = None
    try:
        sc, integ = gsc_conn.client(db, tenant_id, http=http)
        sp = db.begin_nested()  # a failure undoes only this pull's rows
        yesterday = today - timedelta(days=1)
        stored = _gsc_days(sc, db, tenant_id, prop, today - timedelta(days=GSC_RECENT_DAYS), yesterday)
        oldest = today - timedelta(days=GSC_HISTORY_DAYS)
        st = _state(integ)
        done_until = (
            date.fromisoformat(st["backfill_until"])
            if st.get("backfill_until")
            else today - timedelta(days=GSC_RECENT_DAYS)
        )
        if st.get("backfill_property") != prop:  # a new property starts its own backfill
            done_until = today - timedelta(days=GSC_RECENT_DAYS)
        b_end = done_until - timedelta(days=1)
        b_start = max(oldest, b_end - timedelta(days=GSC_BACKFILL_PER_RUN - 1))
        stored += _gsc_days(sc, db, tenant_id, prop, b_start, b_end)
        new_until = min(done_until, b_start)
        sp.commit()
        record_ok(integ, backfill_until=new_until.isoformat(), backfill_property=prop)
        gsc_conn.submit_sitemap_if_changed(db, tenant_id, http=http)
        return {"stored": stored, "more": new_until > oldest}
    except PublishError as exc:
        if sp is not None and sp.is_active:
            sp.rollback()
        st = record_failure(integ, exc)
        log.warning("gsc_pull_failed", tenant_id=tenant_id, status=exc.status, failures=st["failures"])
        return {"failed": True, "status": exc.status, "more": False}


# ── PageSpeed ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def pages_to_check(db: Session, tenant, site, today: date) -> list[tuple[str, str]]:
    """[(label, url)]: home, then stay pages by visits in the last 28 days (website beacon), then the rest in site order."""
    from app.models.website import SitePageView
    from app.services import website_bindings
    from app.services import website_service as wsvc

    base = f"https://{wsvc.primary_host(db, site)}"
    out = [("Home", base + "/")]
    try:
        stays = website_bindings.stay_index(db, tenant, site)
    except Exception:  # noqa: BLE001 -- a classic (v1) site has no stay pages
        stays = []
    since = (today - timedelta(days=28)).isoformat()
    views = dict(
        db.query(SitePageView.path, func.sum(SitePageView.views))
        .filter(
            SitePageView.tenant_id == site.tenant_id,
            SitePageView.site_id == site.id,
            SitePageView.day >= since,
            SitePageView.path.like("/stays/%"),
        )
        .group_by(SitePageView.path)
        .all()
    )
    stays = sorted(stays, key=lambda s: -(views.get(f"/stays/{s.get('slug')}") or 0))
    out += [(str(s.get("name") or s["slug"])[:120], f"{base}/stays/{s['slug']}") for s in stays if s.get("slug")]
    return out[:PSI_PAGES]


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def pull_pagespeed(db: Session, tenant, site, today: date, *, http: httpx.Client | None = None) -> dict:
    if not settings.PAGESPEED_API_KEY:
        return {"skipped": "no_key"}
    if site is None or site.status != "live" or not site.live_version_id:
        return {"skipped": "not_live"}
    wk, done, failed = week_of(today), 0, 0
    for label, url in pages_to_check(db, tenant, site, today):
        for strategy in PSI_STRATEGIES:
            row = db.query(PageSpeedRun).filter_by(tenant_id=tenant.id, url=url, strategy=strategy, week_of=wk).first()
            if row is not None and row.error is None:
                continue  # already measured this week
            row = row or PageSpeedRun(tenant_id=tenant.id, site_id=site.id, url=url, strategy=strategy, week_of=wk)
            row.label, row.measured_at = label, datetime.now(UTC)
            try:
                for k, v in gs.run_pagespeed(url, strategy, settings.PAGESPEED_API_KEY, client=http).items():
                    setattr(row, k, v)
                row.error = None
                done += 1
            except PublishError as exc:
                row.error = ("quota" if exc.status == 429 else f"http {exc.status}" if exc.status else "no answer")[
                    :200
                ]
                failed += 1
                log.warning("pagespeed_failed", tenant_id=tenant.id, status=exc.status)
            db.add(row)
            db.flush()
            if row.error == "quota":  # the rest of this week's pages wait for the retry
                return {"measured": done, "failed": failed, "quota": True}
    return {"measured": done, "failed": failed}


def tenants_to_pull(db: Session) -> list[str]:
    return sorted(
        {
            t
            for (t,) in db.query(Integration.tenant_id).filter(
                Integration.kind.in_((conns.GOOGLE_KIND, gsc_conn.KIND)), Integration.status == "active"
            )
        }
    )
