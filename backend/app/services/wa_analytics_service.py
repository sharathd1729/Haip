"""
WhatsApp messaging dashboard: everything a BSP-style overview shows, computed
from the per-recipient delivery records.

Numbers are read the usual way:
  sent       = every message Meta accepted (so it includes delivered and read)
  delivered  = delivered or read
  read       = read
  delivery rate = delivered / sent      read rate = read / delivered
  failure rate  = failed / (sent + failed)   -- of everything we tried to send

Days are India calendar days. A message belongs to the day it was sent (a read
that happens tomorrow still counts toward today's send), which is how BSP
dashboards attribute it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient
from app.services.wa_campaign_delivery import GROUP_LABELS, describe_error
from app.services.wa_campaign_schedule import IST

MAX_ROWS = 300_000
_SENT = ("sent", "delivered", "read")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pct(part: int, whole: int) -> Optional[float]:
    return round(part / whole * 100, 1) if whole else None


def _ist_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=IST).astimezone(timezone.utc)


def _totals(sent: int, delivered: int, read: int, failed: int) -> dict:
    return {
        "sent": sent, "delivered": delivered, "read": read, "failed": failed,
        "delivery_rate": _pct(delivered, sent),
        "read_rate": _pct(read, delivered),
        "failure_rate": _pct(failed, sent + failed),
    }


def _counts_to_totals(counts: dict[str, int]) -> dict:
    c = {k: counts.get(k, 0) for k in ("queued", "sent", "delivered", "read", "failed")}
    return _totals(c["sent"] + c["delivered"] + c["read"], c["delivered"] + c["read"], c["read"], c["failed"])


def dashboard(db: Session, tenant_id: str, days: int = 30, now: Optional[datetime] = None) -> dict:
    from app.api.v1.endpoints.messaging import WACampaign, WATemplate, TemplateStatus, CampaignStatus

    now = now or datetime.now(timezone.utc)
    days = max(1, min(int(days), 365))
    today = now.astimezone(IST).date()
    first_day = today - timedelta(days=days - 1)
    start = _ist_midnight(first_day)
    end = _ist_midnight(today + timedelta(days=1))
    prev_start = _ist_midnight(first_day - timedelta(days=days))

    rows = (
        db.query(
            Recipient.campaign_id, Recipient.phone, Recipient.status, Recipient.sent_at, Recipient.delivered_at,
            Recipient.read_at, Recipient.failed_at, Recipient.created_at, Recipient.error_code, Recipient.error_reason,
        )
        .filter(Recipient.tenant_id == tenant_id, Recipient.created_at >= start, Recipient.created_at < end)
        .limit(MAX_ROWS + 1)
        .all()
    )
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]

    prev_counts = dict(
        db.query(Recipient.status, func.count(Recipient.id))
        .filter(Recipient.tenant_id == tenant_id, Recipient.created_at >= prev_start, Recipient.created_at < start)
        .group_by(Recipient.status).all()
    )

    daily: dict[date, dict] = {first_day + timedelta(days=i): {"sent": 0, "delivered": 0, "read": 0, "failed": 0} for i in range(days)}
    hours = {h: {"sent": 0, "read": 0} for h in range(24)}
    per_campaign: dict[str, Counter] = defaultdict(Counter)
    fail_groups: dict[str, dict] = {}
    status_counts: Counter = Counter()
    phones: set[str] = set()

    for r in rows:
        status_counts[r.status] += 1
        phones.add(r.phone)
        attempted_at = _aware(r.sent_at) or _aware(r.failed_at) or _aware(r.created_at)
        day = attempted_at.astimezone(IST).date()
        bucket = daily.get(day)
        is_sent, is_delivered, is_read = r.status in _SENT, r.status in ("delivered", "read"), r.status == "read"
        c = per_campaign[r.campaign_id]
        c["total"] += 1
        if bucket is not None:
            if is_sent: bucket["sent"] += 1
            if is_delivered: bucket["delivered"] += 1
            if is_read: bucket["read"] += 1
            if r.status == "failed": bucket["failed"] += 1
        if is_sent: c["sent"] += 1
        if is_delivered: c["delivered"] += 1
        if is_read: c["read"] += 1
        if r.status == "failed":
            c["failed"] += 1
            info = describe_error(r.error_code, r.error_reason)
            g = fail_groups.setdefault(info.group, {"group": info.group, "label": GROUP_LABELS.get(info.group, "Other"),
                                                    "count": 0, "reason": info.reason, "hint": info.hint})
            g["count"] += 1
        if is_sent and r.sent_at:
            h = _aware(r.sent_at).astimezone(IST).hour
            hours[h]["sent"] += 1
            if is_read:
                hours[h]["read"] += 1

    # ── campaigns + templates ──
    campaigns = {c.id: c for c in db.query(WACampaign).filter(WACampaign.tenant_id == tenant_id, WACampaign.id.in_(list(per_campaign) or ["-"]))}
    templates = {t.id: t for t in db.query(WATemplate).filter(WATemplate.tenant_id == tenant_id)}
    campaign_rows, template_acc = [], defaultdict(Counter)
    for cid, c in per_campaign.items():
        camp = campaigns.get(cid)
        tmpl = templates.get(camp.template_id) if camp and camp.template_id else None
        campaign_rows.append({
            "id": cid, "name": camp.name if camp else "Deleted campaign",
            "status": camp.status.value if camp else "deleted",
            "template_name": tmpl.name if tmpl else None,
            "created_at": camp.created_at.isoformat() if camp and camp.created_at else None,
            "total": c["total"], **_totals(c["sent"], c["delivered"], c["read"], c["failed"]),
        })
        key = tmpl.name if tmpl else "(no template)"
        acc = template_acc[key]
        acc["campaigns"] += 1
        for k in ("sent", "delivered", "read", "failed"):
            acc[k] += c[k]
    campaign_rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    template_rows = sorted(
        [{"template_name": k, "campaigns": v["campaigns"], **_totals(v["sent"], v["delivered"], v["read"], v["failed"])} for k, v in template_acc.items()],
        key=lambda r: -(r["sent"] + r["failed"]),
    )

    upcoming = [
        {"id": c.id, "name": c.name, "scheduled_at": c.scheduled_at}
        for c in db.query(WACampaign).filter(WACampaign.tenant_id == tenant_id, WACampaign.status == CampaignStatus.SCHEDULED)
        .order_by(WACampaign.scheduled_at.asc()).limit(10)
    ]
    running = db.query(func.count(WACampaign.id)).filter(WACampaign.tenant_id == tenant_id, WACampaign.status == CampaignStatus.RUNNING).scalar() or 0

    # ── opt-outs in the period ──
    from app.models.consent import Consent
    opt_outs = db.query(func.count(Consent.id)).filter(
        Consent.tenant_id == tenant_id, Consent.scope == "marketing", Consent.granted.is_(False),
        Consent.withdrawn_at >= start.isoformat(), Consent.withdrawn_at < end.isoformat(),
    ).scalar() or 0

    # ── template + connection health ──
    tmpl_status = Counter(t.status.value for t in templates.values())
    from app.models.integration import Integration
    connected = db.query(Integration.id).filter(
        Integration.tenant_id == tenant_id, Integration.kind.in_(("whatsapp_meta", "whatsapp")), Integration.status == "active",
    ).first() is not None

    totals = _counts_to_totals(status_counts)
    prev = _counts_to_totals(prev_counts)
    daily_rows = []
    for d, v in daily.items():
        daily_rows.append({"date": d.isoformat(), **v,
                           "delivery_rate": _pct(v["delivered"], v["sent"]), "read_rate": _pct(v["read"], v["delivered"])})
    hour_rows = [{"hour": h, "sent": v["sent"], "read": v["read"], "read_rate": _pct(v["read"], v["sent"])} for h, v in hours.items()]
    best = max((h for h in hour_rows if h["sent"] >= 20 and h["read_rate"] is not None), key=lambda h: h["read_rate"], default=None)

    return {
        "range": {"days": days, "from": first_day.isoformat(), "to": today.isoformat()},
        "totals": {**totals, "campaigns": len(per_campaign), "contacts": len(phones), "opt_outs": opt_outs},
        "previous": prev,
        "daily": daily_rows,
        "failures": sorted(fail_groups.values(), key=lambda g: -g["count"]),
        "campaigns": campaign_rows[:100],
        "templates": template_rows[:50],
        "hours": hour_rows,
        "best_hour": best["hour"] if best else None,
        "upcoming": upcoming,
        "running": running,
        "health": {"connected": connected, "templates": {k: tmpl_status.get(k, 0) for k in ("approved", "pending", "rejected", "draft", "submission_failed")}},
        "truncated": truncated,
    }
