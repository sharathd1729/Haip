"""Meta ads data for a workspace: which ad account, a daily sync, a backfill of history, and the summary that
joins Meta's numbers to what HAIP sees after the click (leads, bookings, revenue).

The access token is the one the workspace already has. A `meta_ads` integration may carry its own token;
without one we reuse the WhatsApp System User token, which for Ratha holds `ads_read`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.adapters.marketing import meta_ads
from app.core.encryption import decrypt_credentials
from app.models.ad_entity import AdEntity
from app.models.ad_metrics import AdMetric
from app.models.conversation import Conversation
from app.models.integration import Integration
from app.models.lead_attribution import LeadAttribution
from app.models.property import Stay

log = structlog.get_logger()

KIND = "meta_ads"
SYNC_DAYS = 7          # Meta restates recent figures, so each run re-reads the last week
BACKFILL_DAYS = 30     # "Update now"
CHUNK_DAYS = 30        # one Meta request window when loading history
MAX_BACKFILL_MONTHS = 36   # Meta keeps ad insights for about 37 months
UNMATCHED = "__unmatched__"

_METRIC_KEYS = ("campaign_id", "campaign_name", "adset_id", "adset_name", "ad_name", "spend", "impressions", "reach",
                "clicks", "frequency", "ctr", "cpm", "conversations_started", "leads", "currency", "link_clicks",
                "unique_clicks", "post_engagement", "video_views", "first_replies", "cpc", "actions")


class NotConfigured(Exception):
    """No ad account selected, or no token that can read ads."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_row(db: Session, tenant_id: str) -> Optional[Integration]:
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind=KIND).first()


def _token_from(integ: Optional[Integration]) -> str:
    if not integ or not integ.credentials_kms_blob:
        return ""
    try:
        return decrypt_credentials(integ.credentials_kms_blob).get("access_token", "") or ""
    except Exception:
        return ""


def get_token(db: Session, tenant_id: str) -> tuple[str, str]:
    """(token, source). A token saved on the meta_ads integration wins; otherwise the WhatsApp one."""
    own = _token_from(get_row(db, tenant_id))
    if own:
        return own, "meta_ads"
    for kind in ("whatsapp_meta", "whatsapp"):
        tok = _token_from(db.query(Integration).filter_by(tenant_id=tenant_id, kind=kind).first())
        if tok:
            return tok, "whatsapp"
    return "", ""


def status(db: Session, tenant_id: str) -> dict:
    row = get_row(db, tenant_id)
    cfg = (row.config if row else None) or {}
    token, source = get_token(db, tenant_id)
    account = None
    if cfg.get("ad_account_id"):
        account = {"id": cfg.get("ad_account_id"), "name": cfg.get("ad_account_name"), "currency": cfg.get("currency")}
    earliest = None
    if row:
        first = db.query(AdMetric.date).filter(AdMetric.tenant_id == tenant_id).order_by(AdMetric.date.asc()).first()
        earliest = first[0].isoformat() if first else None
    return {
        "configured": bool(row and cfg.get("ad_account_id")),
        "has_token": bool(token), "token_source": source or None,
        "ad_account": account,
        "last_synced_at": cfg.get("last_synced_at"), "last_error": cfg.get("last_error"),
        "backfill": cfg.get("backfill"), "earliest_data": earliest,
    }


def list_accounts(db: Session, tenant_id: str) -> list[dict]:
    token, _ = get_token(db, tenant_id)
    if not token:
        raise NotConfigured("No Meta access token is saved for this workspace.")
    return meta_ads.list_ad_accounts(token)


def select_account(db: Session, tenant_id: str, ad_account_id: str, name: str = "", currency: str = "INR") -> Integration:
    acct = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
    row = get_row(db, tenant_id)
    cfg = {"ad_account_id": acct, "ad_account_name": name, "currency": currency}
    if row is None:
        row = Integration(tenant_id=tenant_id, kind=KIND, status="active", config=cfg, installed_at=_now_iso())
        db.add(row)
    else:
        row.config = {**(row.config or {}), **cfg, "last_error": None}
        row.status = "active"
    db.commit()
    return row


def _mark(db: Session, row: Integration, **cfg) -> None:
    row.config = {**(row.config or {}), **cfg}
    db.commit()


def _require(db: Session, tenant_id: str) -> tuple[Integration, str, str]:
    row = get_row(db, tenant_id)
    acct = ((row.config if row else None) or {}).get("ad_account_id")
    token, _ = get_token(db, tenant_id)
    if not row or not acct or not token:
        raise NotConfigured("Choose an ad account first." if not acct else "No Meta access token is saved for this workspace.")
    return row, acct, token


# ── writing ──────────────────────────────────────────────────────────────────

def _upsert_metrics(db: Session, tenant_id: str, acct: str, rows: list[dict], since: date, until: date) -> tuple[int, int]:
    existing = {
        (m.date, m.ad_id): m for m in db.query(AdMetric).filter(
            AdMetric.tenant_id == tenant_id, AdMetric.date >= since, AdMetric.date <= until)
    }
    created = updated = 0
    for r in rows:
        m = existing.get((r["date"], r["ad_id"]))
        if m is None:
            db.add(AdMetric(tenant_id=tenant_id, ad_account_id=acct, **r))
            created += 1
        else:
            for k in _METRIC_KEYS:
                if k in r:
                    setattr(m, k, r[k])
            m.ad_account_id = acct
            updated += 1
    return created, updated


def _sync_entities(db: Session, tenant_id: str, acct: str, token: str) -> int:
    """Refresh campaign / ad set / ad details. A failure here is logged and does not fail the numbers sync."""
    try:
        rows = list(meta_ads.fetch_entities(token, acct))
    except meta_ads.MetaAdsError as exc:
        log.warning("meta_ads_entities_failed", tenant_id=tenant_id, error=str(exc)[:200])
        return 0
    existing = {(e.level, e.entity_id): e for e in db.query(AdEntity).filter(AdEntity.tenant_id == tenant_id)}
    for r in rows:
        e = existing.get((r["level"], r["entity_id"]))
        if e is None:
            db.add(AdEntity(tenant_id=tenant_id, ad_account_id=acct, **r))
        else:
            for k, v in r.items():
                setattr(e, k, v)
            e.ad_account_id = acct
    return len(rows)


def sync(db: Session, tenant_id: str, days: int = SYNC_DAYS) -> dict:
    """Pull the last `days` days of ad-level insights, and refresh campaign / ad details. Raises NotConfigured
    when there is nothing to sync; a Meta error is recorded on the integration and re-raised."""
    row, acct, token = _require(db, tenant_id)
    until = date.today()
    since = until - timedelta(days=max(1, days) - 1)
    try:
        rows = list(meta_ads.fetch_insights(token, acct, since, until))
    except meta_ads.MetaAdsError as exc:
        _mark(db, row, last_error=str(exc)[:300])
        if exc.bad_token:
            row.status = "error"
            db.commit()
        log.warning("meta_ads_sync_failed", tenant_id=tenant_id, status=exc.status, code=exc.code, rate_limited=exc.rate_limited)
        raise

    created, updated = _upsert_metrics(db, tenant_id, acct, rows, since, until)
    entities = _sync_entities(db, tenant_id, acct, token)
    row.status = "active"
    _mark(db, row, last_synced_at=_now_iso(), last_error=None)
    log.info("meta_ads_synced", tenant_id=tenant_id, created=created, updated=updated, entities=entities)
    return {"created": created, "updated": updated, "entities": entities, "since": since.isoformat(), "until": until.isoformat()}


def backfill_plan(months: int) -> list[tuple[date, date]]:
    """Month-sized windows, newest first, so the recent past appears before the distant one."""
    months = max(1, min(int(months), MAX_BACKFILL_MONTHS))
    until = date.today()
    start = until - timedelta(days=months * 30 - 1)
    windows, hi = [], until
    while hi >= start:
        lo = max(start, hi - timedelta(days=CHUNK_DAYS - 1))
        windows.append((lo, hi))
        hi = lo - timedelta(days=1)
    return windows


def queue_backfill(tenant_id: str, months: int) -> None:
    """Hand a history load to the background worker."""
    from app.workers.tasks.sync_meta_ads import backfill_tenant
    backfill_tenant.apply_async(kwargs={"tenant_id": tenant_id, "months": months}, queue="whatsapp")


def backfill(db: Session, tenant_id: str, months: int = 12) -> dict:
    """Load up to `months` of history, one 30-day window at a time. Progress is saved on the integration after each
    window, so the page can show it. A window Meta refuses is noted and skipped; a rate limit or a rejected token
    stops the run (and says why) so it can be resumed later."""
    row, acct, token = _require(db, tenant_id)
    windows = backfill_plan(months)
    state = {"state": "running", "started_at": _now_iso(), "months": months, "total": len(windows), "done": 0,
             "rows": 0, "failed": [], "stopped_because": None}
    _mark(db, row, backfill=state)

    for lo, hi in windows:
        try:
            rows = list(meta_ads.fetch_insights(token, acct, lo, hi))
        except meta_ads.MetaAdsError as exc:
            if exc.rate_limited or exc.bad_token:
                state.update(state="stopped", stopped_because="rate_limited" if exc.rate_limited else "token_rejected")
                if exc.bad_token:
                    row.status = "error"
                _mark(db, row, backfill=state, last_error=str(exc)[:300])
                log.warning("meta_ads_backfill_stopped", tenant_id=tenant_id, reason=state["stopped_because"])
                return state
            state["failed"].append({"from": lo.isoformat(), "to": hi.isoformat(), "error": str(exc)[:160]})
            state["done"] += 1
            _mark(db, row, backfill=state)
            continue
        created, updated = _upsert_metrics(db, tenant_id, acct, rows, lo, hi)
        state["done"] += 1
        state["rows"] += created + updated
        _mark(db, row, backfill=state)

    state["state"] = "done"
    state["finished_at"] = _now_iso()
    _sync_entities(db, tenant_id, acct, token)
    row.status = "active"
    _mark(db, row, backfill=state, last_synced_at=_now_iso(), last_error=None)
    log.info("meta_ads_backfilled", tenant_id=tenant_id, windows=len(windows), rows=state["rows"], failed=len(state["failed"]))
    return state


# ── reading ──────────────────────────────────────────────────────────────────

def _f(v) -> float:
    return float(v or 0)


def _ratio(n, d, scale=1.0, nd=2) -> Optional[float]:
    return round(n / d * scale, nd) if d else None


def _entity_view(e: Optional[AdEntity]) -> dict:
    if e is None:
        return {}
    return {
        "status": e.status, "effective_status": e.effective_status, "objective": e.objective,
        "optimization_goal": e.optimization_goal, "daily_budget": _f(e.daily_budget) if e.daily_budget is not None else None,
        "lifetime_budget": _f(e.lifetime_budget) if e.lifetime_budget is not None else None,
        "starts_at": e.starts_at.isoformat() if e.starts_at else None, "ends_at": e.ends_at.isoformat() if e.ends_at else None,
    }


class _Acc:
    """Running totals for one campaign or one ad."""
    __slots__ = ("spend", "impressions", "reach", "clicks", "link_clicks", "post_engagement", "video_views",
                 "first_replies", "conversations")

    def __init__(self):
        self.spend = Decimal(0)
        self.impressions = self.reach = self.clicks = self.link_clicks = 0
        self.post_engagement = self.video_views = self.first_replies = self.conversations = 0

    def add(self, m: AdMetric) -> None:
        self.spend += m.spend or 0
        self.impressions += m.impressions or 0
        self.reach += m.reach or 0
        self.clicks += m.clicks or 0
        self.link_clicks += m.link_clicks or 0
        self.post_engagement += m.post_engagement or 0
        self.video_views += m.video_views or 0
        self.first_replies += m.first_replies or 0
        self.conversations += m.conversations_started or 0

    def out(self) -> dict:
        spend = _f(self.spend)
        return {
            "spend": spend, "impressions": self.impressions, "clicks": self.clicks, "link_clicks": self.link_clicks,
            "post_engagement": self.post_engagement, "video_views": self.video_views, "first_replies": self.first_replies,
            "meta_conversations": self.conversations,
            "ctr": _ratio(self.clicks, self.impressions, 100), "cpm": _ratio(spend, self.impressions, 1000),
            "cpc": _ratio(spend, self.clicks), "cost_per_conversation": _ratio(spend, self.conversations),
        }


def summary(db: Session, tenant_id: str, days: int = 30) -> dict:
    until = date.today()
    since = until - timedelta(days=max(1, days) - 1)
    metrics = db.query(AdMetric).filter(
        AdMetric.tenant_id == tenant_id, AdMetric.date >= since, AdMetric.date <= until).all()
    entities = {(e.level, e.entity_id): e for e in db.query(AdEntity).filter(AdEntity.tenant_id == tenant_id)}

    camp, ad_acc = defaultdict(_Acc), defaultdict(_Acc)
    camp_name, camp_ads, ad_info = {}, defaultdict(set), {}
    daily = defaultdict(lambda: {"spend": Decimal(0), "conversations": 0, "impressions": 0, "clicks": 0})
    for m in metrics:
        camp[m.campaign_id].add(m)
        ad_acc[m.ad_id].add(m)
        camp_name[m.campaign_id] = m.campaign_name or camp_name.get(m.campaign_id, "")
        camp_ads[m.campaign_id].add(m.ad_id)
        ad_info[m.ad_id] = {"name": m.ad_name, "adset_id": m.adset_id, "adset_name": m.adset_name, "campaign_id": m.campaign_id}
        d = daily[m.date]
        d["spend"] += m.spend or 0
        d["conversations"] += m.conversations_started or 0
        d["impressions"] += m.impressions or 0
        d["clicks"] += m.clicks or 0

    # ad -> campaign, from every row we hold (an attribution can name an ad that did not run in this window)
    ad_to_campaign = {a: c for a, c in db.query(AdMetric.ad_id, AdMetric.campaign_id).filter(
        AdMetric.tenant_id == tenant_id).distinct()}

    since_dt = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    atts = db.query(LeadAttribution).filter(
        LeadAttribution.tenant_id == tenant_id, LeadAttribution.created_at >= since_dt).all()
    # The link from an ad record to its lead is written only when the lead is created in the same request. When
    # the lead already existed it stays empty, so fall back to the lead the conversation itself points at.
    missing = [a.conversation_id for a in atts if not a.inquiry_id]
    conv_inquiry = dict(db.query(Conversation.id, Conversation.inquiry_id).filter(
        Conversation.tenant_id == tenant_id, Conversation.id.in_(missing))) if missing else {}
    conv_by, inq_by = defaultdict(set), defaultdict(set)
    ad_inq = defaultdict(set)
    for a in atts:
        cid = a.campaign_id or ad_to_campaign.get(a.ad_id or "", "") or UNMATCHED
        conv_by[cid].add(a.conversation_id)
        inquiry_id = a.inquiry_id or conv_inquiry.get(a.conversation_id)
        if inquiry_id:
            inq_by[cid].add(inquiry_id)
            if a.ad_id:
                ad_inq[a.ad_id].add(inquiry_id)

    all_inq = {i for s in inq_by.values() for i in s}
    stays_by_inq = defaultdict(lambda: {"bookings": 0, "revenue": Decimal(0)})
    if all_inq:
        for s in db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.inquiry_id.in_(all_inq), Stay.status != "cancelled"):
            e = stays_by_inq[s.inquiry_id]
            e["bookings"] += 1
            e["revenue"] += s.total_amount or 0

    def haip(inquiries):
        b = sum(stays_by_inq[i]["bookings"] for i in inquiries)
        r = sum((stays_by_inq[i]["revenue"] for i in inquiries), Decimal(0))
        return b, _f(r)

    rows_out = []
    for cid in set(camp) | set(conv_by):
        acc = camp[cid] if cid in camp else None
        base = acc.out() if acc else _Acc().out()
        bookings, revenue = haip(inq_by[cid])
        leads = len(inq_by[cid])
        spend = base["spend"]
        name = camp_name.get(cid) or ("Ads outside the synced account" if cid == UNMATCHED else cid)
        ads_out = []
        for ad_id in sorted(camp_ads.get(cid, ()), key=lambda a: -_f(ad_acc[a].spend)):
            info, aout = ad_info.get(ad_id, {}), ad_acc[ad_id].out()
            ent = entities.get(("ad", ad_id))
            adset = entities.get(("adset", info.get("adset_id", "")))
            ab, ar = haip(ad_inq[ad_id])
            ads_out.append({
                "ad_id": ad_id, "name": (ent.name if ent else "") or info.get("name") or ad_id,
                "adset_id": info.get("adset_id"), "adset_name": (adset.name if adset else "") or info.get("adset_name"),
                **_entity_view(ent), "creative": ent.creative if ent else None,
                "audience": meta_ads.summarize_targeting(adset.targeting) if adset else None,
                **aout, "haip_leads": len(ad_inq[ad_id]), "bookings": ab, "revenue": ar,
                "cost_per_lead": _ratio(aout["spend"], len(ad_inq[ad_id])) if aout["spend"] else None,
                "cost_per_booking": _ratio(aout["spend"], ab) if aout["spend"] else None,
                "roas": _ratio(ar, aout["spend"]) if aout["spend"] else None,
            })
        rows_out.append({
            "campaign_id": cid, "campaign_name": (entities[("campaign", cid)].name if ("campaign", cid) in entities else "") or name,
            **_entity_view(entities.get(("campaign", cid))), **base,
            "ads": len(camp_ads.get(cid, ())), "ad_details": ads_out,
            "haip_conversations": len(conv_by[cid]), "haip_leads": leads, "bookings": bookings, "revenue": revenue,
            # A cost needs both a spend and something it bought; 0 / n would read as "free".
            "cost_per_lead": _ratio(spend, leads) if spend else None,
            "cost_per_booking": _ratio(spend, bookings) if spend else None,     # agency M5: the number that matters
            "roas": _ratio(revenue, spend) if spend else None,
        })
    rows_out.sort(key=lambda r: (-r["spend"], -r["revenue"]))

    tot = _Acc()
    for m in metrics:
        tot.add(m)
    t = tot.out()
    tot_rev = sum(r["revenue"] for r in rows_out)
    tot_haip_conv = sum(r["haip_conversations"] for r in rows_out)
    tot_leads = sum(r["haip_leads"] for r in rows_out)
    return {
        "since": since.isoformat(), "until": until.isoformat(), "days": days,
        "currency": next((m.currency for m in metrics), "INR"),
        "totals": {
            **t, "spend": round(t["spend"], 2),
            "haip_conversations": tot_haip_conv, "haip_leads": tot_leads,
            "bookings": sum(r["bookings"] for r in rows_out), "revenue": round(tot_rev, 2),
            "cost_per_lead": _ratio(t["spend"], tot_leads) if t["spend"] else None,
            "cost_per_booking": _ratio(t["spend"], sum(r["bookings"] for r in rows_out)) if t["spend"] else None,
            "roas": _ratio(tot_rev, t["spend"]) if t["spend"] else None,
            # Meta says N people started a chat; HAIP saw M referrals. A big gap means the ad's attribution is
            # off or messages are being dropped.
            "attribution_gap": max(0, t["meta_conversations"] - tot_haip_conv),
        },
        "campaigns": rows_out,
        "daily": [{"date": d.isoformat(), "spend": _f(v["spend"]), "conversations": v["conversations"],
                   "impressions": v["impressions"], "clicks": v["clicks"]} for d, v in sorted(daily.items())],
    }
