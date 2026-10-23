"""What the ads are doing (agency M5): funnel diagnosis, creative fatigue, and the monthly keep / kill review.

Deterministic, from MEASURED data only: Meta's daily ad metrics (ad_metrics) joined to what HAIP saw after the click
(lead_attribution -> inquiry -> stay, cancelled stays excluded). Every judgement is against THIS account's own median,
never an industry benchmark, and below a minimum of data the answer is "not enough signal", never a guess.

Funnel stages, in the order a guest goes through them, and what to fix when one is weak (< half the account median):
  hook     3-second video views / impressions (videos only)   -> the first 3 seconds / the image
  click    link clicks / impressions                          -> the offer and the first line
  chat     conversations started / link clicks                -> the message button and where it lands
  booking  bookings / conversations                           -> the replies: speed, quote, follow-up
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ad_metrics import AdMetric
from app.models.conversation import Conversation
from app.models.lead_attribution import LeadAttribution
from app.models.property import Stay
from app.models.tenant import Tenant

MIN_IMPRESSIONS = 1000
MIN_REVIEW_SPEND = 500          # rupees: below this an ad has not been tested
FATIGUE_CTR_DROP = 0.7          # recent CTR under 70% of the ad's own first week ...
FATIGUE_FREQUENCY = 2.5         # ... while the same people see it 2.5+ times
ADVICE = {
    "hook": "People scroll past: change the first 3 seconds (or the image) so the place is clear at a glance.",
    "click": "People see it but don't tap: sharpen the offer and the first line (dates, what is included).",
    "chat": "People tap but don't start a chat: check the message button and the greeting they land on.",
    "booking": "Chats don't turn into bookings: look at reply speed, the quote and the follow-up.",
}


def _f(v) -> float:
    return float(v or 0)


def _rate(n, d) -> Optional[float]:
    return round(n / d, 4) if d else None


def per_ad(db: Session, tenant_id: str, since: date, until: date) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "impressions": 0, "clicks": 0, "link_clicks": 0,
                                                 "video_views": 0, "conversations": 0, "days": 0, "thruplays": 0})
    for m in db.query(AdMetric).filter(AdMetric.tenant_id == tenant_id, AdMetric.date >= since, AdMetric.date <= until):
        r = out[m.ad_id]
        r.update(name=m.ad_name or m.ad_id, campaign_id=m.campaign_id, campaign_name=m.campaign_name)
        r["spend"] += _f(m.spend)
        r["impressions"] += m.impressions or 0
        r["clicks"] += m.clicks or 0
        r["link_clicks"] += m.link_clicks or 0
        r["video_views"] += m.video_views or 0
        r["thruplays"] += m.video_thruplays or 0
        r["conversations"] += m.conversations_started or 0
        r["days"] += 1
    return dict(out)


def bookings_by_ad(db: Session, tenant_id: str, since: date, until: date) -> dict[str, dict]:
    """HAIP leads, bookings and revenue per ad, from ad conversations that STARTED in the period."""
    start = datetime.combine(since, time.min, tzinfo=timezone.utc)
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=timezone.utc)
    atts = (db.query(LeadAttribution).filter(LeadAttribution.tenant_id == tenant_id, LeadAttribution.ad_id.isnot(None),
                                             LeadAttribution.created_at >= start, LeadAttribution.created_at < end).all())
    missing = [a.conversation_id for a in atts if not a.inquiry_id]
    conv_inq = dict(db.query(Conversation.id, Conversation.inquiry_id).filter(
        Conversation.tenant_id == tenant_id, Conversation.id.in_(missing))) if missing else {}
    inq_ad: dict[str, str] = {}
    leads = defaultdict(set)
    for a in atts:
        inq = a.inquiry_id or conv_inq.get(a.conversation_id)
        if inq:
            inq_ad.setdefault(inq, a.ad_id)
            leads[a.ad_id].add(inq)
    out = {ad: {"leads": len(v), "bookings": 0, "revenue": 0.0} for ad, v in leads.items()}
    people_and_qualified(db, tenant_id, leads, out)
    if inq_ad:
        for s in db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.inquiry_id.in_(list(inq_ad)),
                                       Stay.status != "cancelled"):
            row = out[inq_ad[s.inquiry_id]]
            row["bookings"] += 1
            row["revenue"] += _f(s.total_amount)
    return out


def people_and_qualified(db: Session, tenant_id: str, inquiries_by_key: dict, out: dict) -> None:
    """Adds `people` (distinct people with a usable phone: guests.lead_identified_at, the lead definition) and
    `qualified` (enquiries passing lead_metrics' qualified rule) to each row of `out`, keyed like inquiries_by_key."""
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    from app.services.lead_metrics import qualified_inquiry_ids
    all_ids = {i for v in inquiries_by_key.values() for i in v}
    if not all_ids:
        return
    guest_of = dict(db.query(Inquiry.id, Inquiry.guest_id).filter(Inquiry.tenant_id == tenant_id, Inquiry.id.in_(all_ids)))
    identified = {g for (g,) in db.query(Guest.id).filter(Guest.tenant_id == tenant_id, Guest.id.in_(set(guest_of.values())),
                                                          Guest.lead_identified_at.isnot(None))}
    qualified = qualified_inquiry_ids(db, tenant_id, all_ids)
    for key, ids in inquiries_by_key.items():
        row = out.setdefault(key, {"leads": len(ids), "bookings": 0, "revenue": 0.0})
        row["people"] = len({guest_of[i] for i in ids if guest_of.get(i) in identified})
        row["qualified"] = sum(1 for i in ids if i in qualified)


def _stages(r: dict) -> dict:
    ctr_clicks = r["link_clicks"] or r["clicks"]
    return {"hook": _rate(r["video_views"], r["impressions"]) if r["video_views"] else None,
            "click": _rate(ctr_clicks, r["impressions"]),
            "chat": _rate(r["conversations"], ctr_clicks) if ctr_clicks else None,
            "booking": _rate(r.get("bookings", 0), r["conversations"]) if r["conversations"] else None}


def diagnose(rows: dict[str, dict]) -> tuple[dict, dict]:
    """(per-ad {stage, advice, rates}, account medians). The first weak stage in funnel order is the one to fix."""
    rates = {ad: _stages(r) for ad, r in rows.items()}
    eligible = [ad for ad, r in rows.items() if r["impressions"] >= MIN_IMPRESSIONS]
    medians = {}
    for stage in ("hook", "click", "chat", "booking"):
        values = [rates[a][stage] for a in eligible if rates[a][stage] is not None]
        medians[stage] = round(median(values), 4) if len(values) >= 2 else None
    out = {}
    for ad, r in rows.items():
        if r["impressions"] < MIN_IMPRESSIONS:
            out[ad] = {"stage": None, "advice": "Not enough signal yet (fewer than 1,000 impressions).", "rates": rates[ad]}
            continue
        weak = None
        for stage in ("hook", "click", "chat", "booking"):
            v, m = rates[ad][stage], medians[stage]
            if stage == "booking" and r["conversations"] >= 10 and not r.get("bookings"):
                weak = stage
                break
            if v is not None and m and v < 0.5 * m:
                weak = stage
                break
        out[ad] = {"stage": weak, "advice": ADVICE[weak] if weak else "No weak stage against your own ads.",
                   "rates": rates[ad]}
    return out, medians


def fatigue(db: Session, tenant_id: str, today: date) -> dict[str, dict]:
    """Ads whose last 3 days' CTR fell under 70% of their own first week while frequency is 2.5+."""
    since = today - timedelta(days=30)
    by_ad = defaultdict(list)
    for m in (db.query(AdMetric).filter(AdMetric.tenant_id == tenant_id, AdMetric.date >= since)
              .order_by(AdMetric.date.asc())):
        by_ad[m.ad_id].append(m)
    out = {}
    for ad, days in by_ad.items():
        if len(days) < 10 or days[-1].date < today - timedelta(days=2):
            continue                                        # too new, or not running now
        first, last = days[:7], days[-3:]
        imp_f, imp_l = sum(d.impressions or 0 for d in first), sum(d.impressions or 0 for d in last)
        if imp_f < 500 or imp_l < 500:
            continue
        ctr_f = sum((d.link_clicks or d.clicks or 0) for d in first) / imp_f
        ctr_l = sum((d.link_clicks or d.clicks or 0) for d in last) / imp_l
        freq = sum(_f(d.frequency) for d in last) / len(last)
        if ctr_f > 0 and ctr_l < FATIGUE_CTR_DROP * ctr_f and freq >= FATIGUE_FREQUENCY:
            out[ad] = {"ctr_first_week": round(ctr_f, 4), "ctr_last_3_days": round(ctr_l, 4),
                       "frequency": round(freq, 2),
                       "advice": "The same people keep seeing it and tap less: swap in a fresh photo or reel."}
    return out


def insights(db: Session, tenant: Tenant, *, days: int = 30, today: Optional[date] = None) -> dict:
    today = today or date.today()
    since = today - timedelta(days=days - 1)
    rows = per_ad(db, tenant.id, since, today)
    for ad, b in bookings_by_ad(db, tenant.id, since, today).items():
        if ad in rows:
            rows[ad].update(b)
    diag, medians = diagnose(rows)
    tired = fatigue(db, tenant.id, today)
    ads = [{"ad_id": ad, **{k: r.get(k) for k in ("name", "campaign_name", "spend", "impressions", "link_clicks",
                                                    "conversations")},
            "bookings": r.get("bookings", 0), "revenue": r.get("revenue", 0.0), **diag[ad], "fatigue": tired.get(ad)}
           for ad, r in sorted(rows.items(), key=lambda x: -x[1]["spend"])]
    return {"since": since.isoformat(), "until": today.isoformat(), "medians": medians, "ads": ads}


def monthly_review(db: Session, tenant: Tenant, month: date) -> dict:
    """Keep / kill / test more for every ad that spent in the month, by cost per booking against the account."""
    start = month.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    rows = per_ad(db, tenant.id, start, end)
    for ad, b in bookings_by_ad(db, tenant.id, start, end).items():
        if ad in rows:
            rows[ad].update(b)
    cpbs = [r["spend"] / r["bookings"] for r in rows.values() if r.get("bookings")]
    med = median(cpbs) if cpbs else None
    out = []
    for ad, r in sorted(rows.items(), key=lambda x: -x[1]["spend"]):
        b, spend, rev = r.get("bookings", 0), r["spend"], r.get("revenue", 0.0)
        cpb = spend / b if b else None
        roas = rev / spend if spend else None
        if spend < MIN_REVIEW_SPEND:
            verdict, why = "test_more", f"Spent under Rs {MIN_REVIEW_SPEND}: not tested yet."
        elif b and ((med is not None and cpb <= med * 1.2) or (roas is not None and roas >= 3)):
            verdict, why = "keep", "Brings bookings at or below your usual cost." if med else "Brings bookings."
        elif not b and spend >= (2 * med if med else 3000):
            verdict, why = "kill", "Spent a lot with no booking."
        else:
            verdict, why = "test_more", "Some signal; give it another round or a fresh creative."
        out.append({"ad_id": ad, "name": r.get("name"), "campaign_name": r.get("campaign_name"),
                    "spend": round(spend, 2), "conversations": r["conversations"], "leads": r.get("leads", 0),
                    "bookings": b, "revenue": round(rev, 2),
                    "cost_per_booking": round(cpb, 2) if cpb is not None else None,
                    "roas": round(roas, 2) if roas is not None else None, "verdict": verdict, "why": why})
    spend = sum(r["spend"] for r in out)
    bookings = sum(r["bookings"] for r in out)
    revenue = sum(r["revenue"] for r in out)
    return {"month": start.isoformat()[:7], "since": start.isoformat(), "until": end.isoformat(),
            "totals": {"spend": round(spend, 2), "bookings": bookings, "revenue": round(revenue, 2),
                       "cost_per_booking": round(spend / bookings, 2) if bookings else None,
                       "roas": round(revenue / spend, 2) if spend else None,
                       "meta_conversations": sum(r["conversations"] for r in out),
                       "haip_leads": sum(r["leads"] for r in out),
                       "median_cost_per_booking": round(med, 2) if med else None},
            "ads": out}
