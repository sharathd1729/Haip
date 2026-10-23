"""The analyst's journey numbers for one period, in code only (never the model).

Every KPI that already has a definition is READ from its owner, never re-stated:
  leads.identified_new, contacts.unidentified, conversations.new, the lead cohort  -> lead_metrics
  stays.booked_value, payments.collected                                           -> kpi_metrics
  received -> seen -> called -> contacted -> proposal -> sold (cohort of enquiries received in the period)
                                                                                   -> workflow_report_service.report
New, analyst-only figures (catalogue section 17): ads spend / chats / cost per chat for an arbitrary period (ad_metrics),
contacts.to_lead (people first heard from in the period who are leads by now), validity reviewed by a person
(inquiries.validation_status), lost reasons and the segment tables below.

Segments (each row {key, label, n, x, rate} with x = the outcome the segment is judged on): channel (first touch, leads ->
booked), source (enquiries -> won), campaign (ad spend -> chats -> leads), package (quotes -> won), agent (leads -> booked),
weekday/hour of the first message (contacts -> lead) and group size (enquiries -> won).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ad_metrics import AdMetric
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.lead_attribution import LeadAttribution
from app.models.pipeline_stage import PipelineStage
from app.services import kpi_metrics, lead_metrics
from app.services.date_presets import IST

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _f(v) -> float:
    return float(v or 0)


def _row(key: str, label: str, n: int, x: int, **extra) -> dict:
    return {"key": key, "label": label, "n": int(n), "x": int(x), "rate": round(x / n, 4) if n else None, **extra}


def ads(db: Session, tenant_id: str, d_from: date, d_to: date, lo: datetime, hi: datetime) -> dict:
    rows = db.query(AdMetric.campaign_id, AdMetric.campaign_name, AdMetric.ad_id, AdMetric.ad_name,
                    func.coalesce(func.sum(AdMetric.spend), 0), func.coalesce(func.sum(AdMetric.conversations_started), 0)
                    ).filter(AdMetric.tenant_id == tenant_id, AdMetric.date >= d_from, AdMetric.date <= d_to
                             ).group_by(AdMetric.campaign_id, AdMetric.campaign_name, AdMetric.ad_id, AdMetric.ad_name).all()
    camp: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "chats": 0, "name": ""})
    by_ad = []
    for cid, cname, aid, aname, spend, chats in rows:
        c = camp[cid or "unknown"]
        c["spend"] += _f(spend)
        c["chats"] += int(chats or 0)
        c["name"] = cname or c["name"] or (cid or "")
        by_ad.append({"key": aid, "label": aname or aid, "spend": round(_f(spend), 2), "chats": int(chats or 0),
                      "cost_per_chat": round(_f(spend) / chats, 2) if chats else None})
    leads_by_campaign = Counter(c or "unknown" for (c,) in db.query(LeadAttribution.campaign_id).filter(
        LeadAttribution.tenant_id == tenant_id, LeadAttribution.created_at >= lo, LeadAttribution.created_at <= hi,
        LeadAttribution.inquiry_id.isnot(None)).all())
    spend = sum(c["spend"] for c in camp.values())
    chats = sum(c["chats"] for c in camp.values())
    campaigns = sorted(({"key": k, "label": v["name"], "spend": round(v["spend"], 2), "chats": v["chats"],
                         "cost_per_chat": round(v["spend"] / v["chats"], 2) if v["chats"] else None,
                         "leads": leads_by_campaign.get(k, 0)} for k, v in camp.items()), key=lambda r: -r["spend"])
    return {"spend": round(spend, 2), "chats_started": chats, "cost_per_chat": round(spend / chats, 2) if chats else None,
            "traced_leads": sum(leads_by_campaign.values()), "campaigns": campaigns[:8],
            "ads": sorted(by_ad, key=lambda r: -r["spend"])[:8], "connected": bool(rows)}


def conversations(db: Session, tenant_id: str, lo: datetime, hi: datetime) -> dict:
    by = {k: lead_metrics.count_conversations(db, tenant_id, lo, hi, channel=k) for k in ("whatsapp", "instagram", "website", "call")}
    bridge = int(db.query(func.count(Conversation.id)).filter(
        Conversation.tenant_id == tenant_id, Conversation.source == "personal_bridge",
        Conversation.created_at >= lo, Conversation.created_at <= hi).scalar() or 0)
    return {"total": lead_metrics.count_conversations(db, tenant_id, lo, hi), "by_channel": by,
            "personal_whatsapp": bridge, "whatsapp_business": max(0, by["whatsapp"] - bridge)}


def contacts_to_lead(db: Session, tenant_id: str, lo: datetime, hi: datetime) -> dict:
    """contacts.to_lead: people first heard from in the period (Guest.created_at), and how many are leads (phone) by now."""
    base = [*lead_metrics.people(tenant_id), Guest.created_at >= lo, Guest.created_at <= hi]
    n = int(db.query(func.count(Guest.id)).filter(*base).scalar() or 0)
    x = int(db.query(func.count(Guest.id)).filter(*base, Guest.lead_identified_at.isnot(None)).scalar() or 0)
    return {"n": n, "x": x, "rate": round(x / n, 4) if n else None}


def _lost_reason(inq: Inquiry) -> str:
    """The recorded outcome reason when the parallel branch's column exists (171), else the stage-move lost reason, else the AI's
    reading of the lead (ai_analysis.blocking_objection), else "not recorded"."""
    reason = getattr(inq, "outcome_reason", None)
    if reason:
        return str(reason)
    lr = getattr(inq.lost_reason, "value", inq.lost_reason)
    if lr:
        return str(lr)
    ai = inq.ai_analysis if isinstance(inq.ai_analysis, dict) else {}
    obj = ai.get("blocking_objection")
    if isinstance(obj, dict):
        obj = obj.get("type") or obj.get("objection")
    return f"ai:{str(obj)[:40]}" if obj else "not_recorded"


def enquiries(db: Session, tenant_id: str, lo: datetime, hi: datetime) -> dict:
    """Guest enquiries created in the period: reviewed validity, won / lost (stage flags) and why lost."""
    rows = (db.query(Inquiry, PipelineStage.is_closed_won, PipelineStage.is_closed_lost, PipelineStage.category)
            .outerjoin(PipelineStage, PipelineStage.id == Inquiry.stage_id)
            .filter(*kpi_metrics.lead_filters(tenant_id, lo, hi)).all())
    won = [i for i, w, _l, _c in rows if w]
    lost = [i for i, _w, lo_, _c in rows if lo_]
    reviewed = [i for i, *_ in rows if i.validation_status in ("valid", "invalid")]
    reasons = Counter(_lost_reason(i) for i in lost)
    return {"created": len(rows), "stage_valid": sum(1 for *_x, c in rows if c == "valid"),
            "reviewed": len(reviewed), "reviewed_valid": sum(1 for i in reviewed if i.validation_status == "valid"),
            "won": len(won), "lost": len(lost),
            "lost_reasons": [{"reason": k, "count": n} for k, n in reasons.most_common(8)],
            "_rows": rows}


def quotes(db: Session, tenant_id: str, lo: datetime, hi: datetime) -> dict:
    """Quotes created in the period (one per option group), how many were shared and accepted, by package."""
    rows = db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.created_at >= lo,
                                         InquiryQuote.created_at <= hi).all()
    groups: dict[str, InquiryQuote] = {}
    for q in rows:
        g = q.option_group_id or q.id
        if g not in groups or (q.option_rank or 1) < (groups[g].option_rank or 1):
            groups[g] = q
    by_pkg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for q in groups.values():
        k = q.package_key or "custom"
        by_pkg[k][0] += 1
        by_pkg[k][1] += 1 if q.status == "accepted" else 0
    return {"created": len(groups), "shared": sum(1 for q in groups.values() if q.shared_at),
            "accepted": sum(1 for q in groups.values() if q.status == "accepted"),
            "amounts": [float(q.amount) for q in groups.values() if q.amount],
            "by_package": sorted((_row(k, k, v[0], v[1]) for k, v in by_pkg.items()), key=lambda r: -r["n"])[:10]}


def revenue(db: Session, tenant_id: str, d_from: date, d_to: date, lo: datetime, hi: datetime) -> dict:
    bv = kpi_metrics.booked_value(db, tenant_id, lo, hi)
    cash = kpi_metrics.payment_totals(db, tenant_id, d_from, d_to)
    return {"bookings": bv["count"], "booked_value": round(bv["total"], 2), "rental": round(bv["rental"], 2),
            "add_ons": round(bv["add_ons"], 2), "collected": round(cash["collected"], 2), "refunded": round(cash["refunded"], 2)}


def segments(db: Session, tenant_id: str, lo: datetime, hi: datetime, enq_rows: list, quote_block: dict) -> dict:
    channel = [_row(r["key"], r["label"], r["leads"], r["bookings"], value=round(r["value"], 2))
               for r in lead_metrics.by_first_touch(db, tenant_id, lo, hi, with_bookings=True)]
    src: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    size: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for inq, won, _l, _c in enq_rows:
        k = getattr(inq.source, "value", inq.source) or "not_recorded"
        src[k][0] += 1
        src[k][1] += 1 if won else 0
        n = int(inq.adults or 0) + int(inq.children or 0)
        band = "unknown" if n <= 0 else ("1-2" if n <= 2 else "3-4" if n <= 4 else "5-6" if n <= 6 else "7+")
        size[band][0] += 1
        size[band][1] += 1 if won else 0
    owners = lead_metrics.by_owner(db, tenant_id, lo, hi, with_bookings=True)
    from app.models.user import User
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == tenant_id, User.id.in_([u for u in owners if u])).all()) if owners else {}
    agent = [_row(uid or "unassigned", names.get(uid, "Unassigned") if uid else "Unassigned", v["leads"], v["bookings"])
             for uid, v in owners.items()]
    # weekday / hour of the conversation's opening (IST): contacts -> lead
    wd: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    hr: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for created, identified in (db.query(Conversation.created_at, Guest.lead_identified_at)
                                .join(Guest, Guest.id == Conversation.guest_id)
                                .filter(Conversation.tenant_id == tenant_id, Conversation.channel != ChannelType.INTERNAL,
                                        Conversation.created_at >= lo, Conversation.created_at <= hi,
                                        Guest.is_sample.is_(False)).all()):
        local = kpi_metrics.as_datetime(created).astimezone(IST)
        for bucket, key in ((wd, WEEKDAYS[local.weekday()]), (hr, f"{local.hour:02d}")):
            bucket[key][0] += 1
            bucket[key][1] += 1 if identified else 0
    return {
        "channel": channel,
        "source": sorted((_row(k, k, v[0], v[1]) for k, v in src.items()), key=lambda r: -r["n"]),
        "package": quote_block["by_package"],
        "agent": sorted(agent, key=lambda r: -r["n"]),
        "weekday": [_row(k, k, wd[k][0], wd[k][1]) for k in WEEKDAYS if k in wd],
        "hour": [_row(k, f"{k}:00", hr[k][0], hr[k][1]) for k in sorted(hr)],
        "group_size": sorted((_row(k, k, v[0], v[1]) for k, v in size.items()), key=lambda r: r["key"]),
    }


def journey(db: Session, tenant_id: str, d_from: date, d_to: date, lo: datetime, hi: datetime) -> dict:
    from app.services import workflow_report_service as wrs
    wf = wrs.report(db, tenant_id, d_from, d_to)
    enq = enquiries(db, tenant_id, lo, hi)
    rows = enq.pop("_rows")
    q = quotes(db, tenant_id, lo, hi)
    cohort = lead_metrics.cohort(db, tenant_id, lo, hi)
    steps = {s["key"]: s["count"] for s in wf["funnel"]}
    return {
        "ads": ads(db, tenant_id, d_from, d_to, lo, hi),
        "conversations": conversations(db, tenant_id, lo, hi),
        "contacts": {"unidentified": lead_metrics.count_unidentified_contacts(db, tenant_id, lo, hi),
                     "to_lead": contacts_to_lead(db, tenant_id, lo, hi)},
        "leads": {"new": lead_metrics.count_new_leads(db, tenant_id, lo, hi), "cohort": cohort,
                  "lead_to_booking": lead_metrics.lead_to_booking(cohort)},
        "enquiries": enq,
        "workflow": {"received": steps.get("received", 0), "seen": steps.get("seen", 0), "called": steps.get("called", 0),
                     "contacted": steps.get("contacted", 0), "proposal": steps.get("proposal", 0),
                     "followed_up": steps.get("followed_up", 0), "sold": steps.get("sold", 0),
                     "median_first_contact_minutes": wf["summary"]["median_first_contact_minutes"],
                     "biggest_drop": wf["biggest_drop"], "lost_reasons": wf["lost_reasons"]},
        "quotes": {k: v for k, v in q.items() if k != "amounts"},
        "revenue": revenue(db, tenant_id, d_from, d_to, lo, hi),
        "segments": segments(db, tenant_id, lo, hi, rows, q),
        "_workflow_agents": wf["agents"],
        "_quote_amounts": q["amounts"],
    }
