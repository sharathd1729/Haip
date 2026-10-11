"""Meta ads data for a workspace: which ad account, a daily sync, and the summary that joins Meta's
numbers to what HAIP sees after the click (leads, bookings, revenue).

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
from app.models.ad_metrics import AdMetric
from app.models.conversation import Conversation
from app.models.integration import Integration
from app.models.lead_attribution import LeadAttribution
from app.models.property import Stay

log = structlog.get_logger()

KIND = "meta_ads"
SYNC_DAYS = 7          # Meta restates recent figures, so each run re-reads the last week
BACKFILL_DAYS = 30     # first sync, and "Sync now"
UNMATCHED = "__unmatched__"


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
    return {
        "configured": bool(row and cfg.get("ad_account_id")),
        "has_token": bool(token), "token_source": source or None,
        "ad_account": account,
        "last_synced_at": cfg.get("last_synced_at"), "last_error": cfg.get("last_error"),
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


def sync(db: Session, tenant_id: str, days: int = SYNC_DAYS) -> dict:
    """Pull the last `days` days of ad-level insights and upsert them. Raises NotConfigured when there is
    nothing to sync; a Meta error is recorded on the integration and re-raised."""
    row = get_row(db, tenant_id)
    acct = ((row.config if row else None) or {}).get("ad_account_id")
    token, _ = get_token(db, tenant_id)
    if not row or not acct or not token:
        raise NotConfigured("Choose an ad account first." if not acct else "No Meta access token is saved for this workspace.")

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
            for k, v in r.items():
                setattr(m, k, v)
            m.ad_account_id = acct
            updated += 1
    row.status = "active"
    _mark(db, row, last_synced_at=_now_iso(), last_error=None)
    log.info("meta_ads_synced", tenant_id=tenant_id, created=created, updated=updated)
    return {"created": created, "updated": updated, "since": since.isoformat(), "until": until.isoformat()}


def _f(v) -> float:
    return float(v or 0)


def summary(db: Session, tenant_id: str, days: int = 30) -> dict:
    until = date.today()
    since = until - timedelta(days=max(1, days) - 1)
    metrics = db.query(AdMetric).filter(
        AdMetric.tenant_id == tenant_id, AdMetric.date >= since, AdMetric.date <= until).all()

    camp = defaultdict(lambda: {"campaign_name": "", "spend": Decimal(0), "impressions": 0, "reach": 0, "clicks": 0,
                                "conversations_started": 0, "ads": set()})
    daily = defaultdict(lambda: {"spend": Decimal(0), "conversations_started": 0})
    for m in metrics:
        c = camp[m.campaign_id]
        c["campaign_name"] = m.campaign_name or c["campaign_name"]
        c["spend"] += m.spend or 0
        c["impressions"] += m.impressions or 0
        c["reach"] += m.reach or 0
        c["clicks"] += m.clicks or 0
        c["conversations_started"] += m.conversations_started or 0
        c["ads"].add(m.ad_id)
        d = daily[m.date]
        d["spend"] += m.spend or 0
        d["conversations_started"] += m.conversations_started or 0

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
    for a in atts:
        cid = a.campaign_id or ad_to_campaign.get(a.ad_id or "", "") or UNMATCHED
        conv_by[cid].add(a.conversation_id)
        inquiry_id = a.inquiry_id or conv_inquiry.get(a.conversation_id)
        if inquiry_id:
            inq_by[cid].add(inquiry_id)

    all_inq = {i for s in inq_by.values() for i in s}
    stays_by_inq = defaultdict(lambda: {"bookings": 0, "revenue": Decimal(0)})
    if all_inq:
        for s in db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.inquiry_id.in_(all_inq), Stay.status != "cancelled"):
            e = stays_by_inq[s.inquiry_id]
            e["bookings"] += 1
            e["revenue"] += s.total_amount or 0

    rows_out = []
    for cid in set(camp) | set(conv_by):
        c = camp.get(cid)
        spend = c["spend"] if c else Decimal(0)
        bookings = sum(stays_by_inq[i]["bookings"] for i in inq_by[cid])
        revenue = sum((stays_by_inq[i]["revenue"] for i in inq_by[cid]), Decimal(0))
        leads = len(inq_by[cid])
        meta_conv = c["conversations_started"] if c else 0
        name = (c["campaign_name"] if c else "") or ("Ads outside the synced account" if cid == UNMATCHED else cid)
        rows_out.append({
            "campaign_id": cid, "campaign_name": name,
            "spend": _f(spend), "impressions": c["impressions"] if c else 0, "reach": c["reach"] if c else 0,
            "clicks": c["clicks"] if c else 0, "ads": len(c["ads"]) if c else 0,
            "meta_conversations": meta_conv, "haip_conversations": len(conv_by[cid]), "haip_leads": leads,
            "bookings": bookings, "revenue": _f(revenue),
            # A cost needs both a spend and something it bought; 0 / n would read as "free".
            "cost_per_conversation": round(_f(spend) / meta_conv, 2) if meta_conv and spend else None,
            "cost_per_lead": round(_f(spend) / leads, 2) if leads and spend else None,
            "roas": round(_f(revenue) / _f(spend), 2) if spend else None,
        })
    rows_out.sort(key=lambda r: (-r["spend"], -r["revenue"]))

    tot_spend = sum(r["spend"] for r in rows_out)
    tot_rev = sum(r["revenue"] for r in rows_out)
    tot_conv = sum(r["meta_conversations"] for r in rows_out)
    tot_haip_conv = sum(r["haip_conversations"] for r in rows_out)
    tot_leads = sum(r["haip_leads"] for r in rows_out)
    return {
        "since": since.isoformat(), "until": until.isoformat(), "days": days,
        "currency": next((m.currency for m in metrics), "INR"),
        "totals": {
            "spend": round(tot_spend, 2), "impressions": sum(r["impressions"] for r in rows_out),
            "reach": sum(r["reach"] for r in rows_out), "clicks": sum(r["clicks"] for r in rows_out),
            "meta_conversations": tot_conv, "haip_conversations": tot_haip_conv, "haip_leads": tot_leads,
            "bookings": sum(r["bookings"] for r in rows_out), "revenue": round(tot_rev, 2),
            "cost_per_conversation": round(tot_spend / tot_conv, 2) if tot_conv else None,
            "cost_per_lead": round(tot_spend / tot_leads, 2) if tot_leads else None,
            "roas": round(tot_rev / tot_spend, 2) if tot_spend else None,
            # Meta says N people started a chat; HAIP saw M referrals. A big gap means the ad's attribution is
            # off or messages are being dropped.
            "attribution_gap": max(0, tot_conv - tot_haip_conv),
        },
        "campaigns": rows_out,
        "daily": [{"date": d.isoformat(), "spend": _f(v["spend"]), "conversations": v["conversations_started"]}
                  for d, v in sorted(daily.items())],
    }
