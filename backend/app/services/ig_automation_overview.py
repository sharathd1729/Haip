"""The Instagram automations dashboard (Instagram Automations v2, phase 2): what the automations did in a period,
compared with the period before, from comment to booking; which posts bring leads; and what needs a look.

Read-only. Numbers come from ig_automation_events (one row per step an automation took), guests.lead_identified_at
(the one lead rule: a usable phone number), stays (cancelled ones left out) and the comment messages HAIP stored.
Periods are HAIP's presets, resolved in IST (services/date_presets.py).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.models.guest import Guest
from app.models.ig_automation import IgAutomationEvent
from app.services import date_presets

PERIODS = ("today", "yesterday", "last_7d", "this_month", "last_month")
IG_ACTION = "send_instagram_quick_reply"
COMMENT_TRIGGERS = ("ig_comment_received", "ig_live_comment_received")
MAX_COMMENT_ROWS = 5000  # comment messages read per period for the "no automation" lists


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def windows(period: str) -> tuple[tuple[date, date, datetime, datetime], tuple[date, date, datetime, datetime]]:
    """(current, previous) as (from, to, start_utc, end_utc). The previous window is the same length right before,
    except "this month", which is compared with the same days of last month."""
    if period not in PERIODS:
        raise ValueError(f"Unknown period: {period}")
    d_from, d_to = date_presets.resolve_preset(period)
    if period == "this_month":
        last_of_prev = d_from - timedelta(days=1)
        p_from = last_of_prev.replace(day=1)
        p_to = min(p_from + (d_to - d_from), last_of_prev)
    elif period == "last_month":
        p_to = d_from - timedelta(days=1)
        p_from = p_to.replace(day=1)
    else:
        length = d_to - d_from
        p_to = d_from - timedelta(days=1)
        p_from = p_to - length

    def utc(a: date, b: date):
        _, _, s, e = date_presets.ist_range_to_utc(a.isoformat(), b.isoformat())
        return a, b, s, e

    return utc(d_from, d_to), utc(p_from, p_to)


def _events(db: Session, tenant_id: str, start: datetime, end: datetime, kinds) -> list[IgAutomationEvent]:
    return (
        db.query(IgAutomationEvent)
        .filter(
            IgAutomationEvent.tenant_id == tenant_id,
            IgAutomationEvent.kind.in_(kinds),
            IgAutomationEvent.created_at >= start,
            IgAutomationEvent.created_at <= end,
        )
        .all()
    )


def _reach(db: Session, tenant_id: str, start: datetime, end: datetime) -> dict:
    """Everything that hangs off "people reached" in a window: per (rule, guest) the first DM and its post; who became
    a lead after it (by the window's end); and their bookings made after it."""
    from app.models.property import Stay

    sent = _events(db, tenant_id, start, end, ("dm_sent",))
    first: dict[tuple[str, str], tuple[datetime, str | None]] = {}
    for e in sent:
        if not e.guest_id:
            continue
        key = (e.rule_id, e.guest_id)
        at = _aware(e.created_at)
        if key not in first or at < first[key][0]:
            first[key] = (at, e.media_id)
    guests = {g for _, g in first}
    lead_at = dict(
        db.query(Guest.id, Guest.lead_identified_at)
        .filter(Guest.tenant_id == tenant_id, Guest.id.in_(guests or {""}), Guest.lead_identified_at.isnot(None))
        .all()
    )
    earliest: dict[str, datetime] = {}
    for (_, g), (at, _) in first.items():
        earliest[g] = min(at, earliest.get(g, at))
    leads = {g for g, at in earliest.items() if lead_at.get(g) and earliest[g] <= _aware(lead_at[g]) <= end}
    stays = (
        db.query(Stay.guest_id, Stay.total_amount, Stay.created_at)
        .filter(Stay.tenant_id == tenant_id, Stay.guest_id.in_(leads or {""}), Stay.status != "cancelled")
        .all()
    )
    booked: dict[str, float] = defaultdict(float)
    for guest_id, amount, created in stays:
        c = _aware(created)
        if c is not None and earliest[guest_id] <= c <= end:
            booked[guest_id] += float(amount or 0)
    return {"first": first, "earliest": earliest, "leads": leads, "booked": dict(booked), "sent": sent}


def _kpis(db: Session, tenant_id: str, start: datetime, end: datetime, money: bool) -> dict:
    r = _reach(db, tenant_id, start, end)
    counts = dict(
        db.query(IgAutomationEvent.kind, func.count())
        .filter(
            IgAutomationEvent.tenant_id == tenant_id,
            IgAutomationEvent.created_at >= start,
            IgAutomationEvent.created_at <= end,
        )
        .group_by(IgAutomationEvent.kind)
        .all()
    )
    opened = len({(e.rule_id, e.guest_id) for e in _events(db, tenant_id, start, end, ("opened",))})
    return {
        "comments_answered": sum(1 for e in r["sent"] if e.media_id),
        "dms_sent": counts.get("dm_sent", 0),
        "opened": opened,
        "clicked": counts.get("clicked", 0),
        "forms_started": counts.get("form_started", 0),
        "forms_completed": counts.get("form_completed", 0),
        "triggered": counts.get("triggered", 0),
        "leads": len(r["leads"]),
        "bookings": len(r["booked"]),
        "booked_amount": round(sum(r["booked"].values()), 2) if money else None,
        "_reach": r,
    }


def _comment_rows(db: Session, tenant_id: str, start: datetime, end: datetime) -> list[dict]:
    """The comments HAIP stored in a window: [{media_id, ad_id, ad_title, at}] (channel_metadata of comment messages)."""
    from app.models.conversation import Message, MessageDirection

    rows = (
        db.query(Message.channel_metadata, Message.created_at)
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.INBOUND,
            Message.channel_message_id.like("comment_%"),
            Message.created_at >= start,
            Message.created_at <= end,
        )
        .order_by(Message.created_at.desc())
        .limit(MAX_COMMENT_ROWS)
        .all()
    )
    out = []
    for meta, at in rows:
        meta = meta if isinstance(meta, dict) else {}
        if meta.get("media_id"):
            out.append(
                {
                    "media_id": str(meta["media_id"]),
                    "ad_id": str(meta.get("media_ad_id") or "") or None,
                    "ad_title": meta.get("media_ad_title"),
                    "at": _aware(at),
                }
            )
    return out


def _coverage(db: Session, tenant_id: str) -> tuple[bool, set[str], set[str]]:
    """(an active rule answers comments on any post?, post ids with their own rule, ad ids with their own rule)."""
    any_post, posts, ads = False, set(), set()
    rules = (
        db.query(AutomationRule)
        .filter(
            AutomationRule.tenant_id == tenant_id,
            AutomationRule.is_active.is_(True),
            AutomationRule.action == IG_ACTION,
            AutomationRule.trigger.in_(COMMENT_TRIGGERS),
        )
        .all()
    )
    for r in rules:
        tc = r.trigger_config or {}
        scope = tc.get("scope") or ("post" if tc.get("media_id") else "any")
        if tc.get("ad_id"):
            ads.add(str(tc["ad_id"]))
        elif tc.get("media_id"):  # one post, or a "next post" rule already bound to its post
            posts.add(str(tc["media_id"]))
        elif scope == "any" and r.trigger == "ig_comment_received":
            any_post = True
    return any_post, posts, ads


def overview(db: Session, tenant_id: str, period: str, *, money: bool) -> dict:
    (f, t, start, end), (pf, pt, pstart, pend) = windows(period)
    cur = _kpis(db, tenant_id, start, end, money)
    prev = _kpis(db, tenant_id, pstart, pend, money)
    reach = cur.pop("_reach")
    prev.pop("_reach")

    # Top posts: per post (media of the first DM), people reached, opened, leads, bookings.
    opened_pairs = {(e.rule_id, e.guest_id) for e in _events(db, tenant_id, start, end, ("opened",))}
    posts: dict[str, dict] = {}
    for (rule_id, guest_id), (_, media_id) in reach["first"].items():
        if not media_id:
            continue
        p = posts.setdefault(
            media_id, {"media_id": media_id, "people": set(), "opened": 0, "leads": set(), "booked": set()}
        )
        p["people"].add(guest_id)
        if (rule_id, guest_id) in opened_pairs:
            p["opened"] += 1
        if guest_id in reach["leads"]:
            p["leads"].add(guest_id)
        if guest_id in reach["booked"]:
            p["booked"].add(guest_id)
    top = []
    for p in posts.values():
        amount = sum(reach["booked"][g] for g in p["booked"])
        top.append(
            {
                "media_id": p["media_id"],
                "people": len(p["people"]),
                "opened": p["opened"],
                "leads": len(p["leads"]),
                "bookings": len(p["booked"]),
                "booked_amount": round(amount, 2) if money else None,
            }
        )
    top.sort(key=lambda x: (x["bookings"], x["leads"], x["people"]), reverse=True)

    # Posts and ads getting comments with no automation of their own.
    any_post, covered_posts, covered_ads = _coverage(db, tenant_id)
    comments = _comment_rows(db, tenant_id, start, end)
    uncovered: dict[str, dict] = {}
    ads: dict[str, dict] = {}
    for c in comments:
        if c["ad_id"]:
            if c["ad_id"] not in covered_ads and c["media_id"] not in covered_posts and not any_post:
                a = ads.setdefault(
                    c["ad_id"], {"ad_id": c["ad_id"], "title": c["ad_title"], "media_id": c["media_id"], "comments": 0}
                )
                a["comments"] += 1
            continue
        if any_post or c["media_id"] in covered_posts:
            continue
        # rows come newest first, so the first one seen per post is its latest comment
        u = uncovered.setdefault(c["media_id"], {"media_id": c["media_id"], "comments": 0, "last_at": c["at"]})
        u["comments"] += 1
    without = sorted(uncovered.values(), key=lambda x: x["comments"], reverse=True)[:10]
    for w in without:
        w["last_at"] = w["last_at"].isoformat() if w["last_at"] else None

    skipped = _events(db, tenant_id, start, end, ("skipped",))
    other_app = sum(1 for e in skipped if (e.detail or "") == "comment_already_answered")
    alerts = []
    if ads:
        top_ad = max(ads.values(), key=lambda a: a["comments"])
        alerts.append(
            {
                "kind": "ads_without_automation",
                "severity": "critical",
                "count": len(ads),
                "detail": top_ad.get("title") or None,
                "media_id": top_ad["media_id"],
            }
        )
    if other_app:
        alerts.append({"kind": "other_app_answered_first", "severity": "warning", "count": other_app})
    failed = len(_events(db, tenant_id, start, end, ("dm_failed",)))
    if failed:
        alerts.append({"kind": "sends_failed", "severity": "warning", "count": failed})
    if without:
        alerts.append(
            {
                "kind": "post_without_automation",
                "severity": "info",
                "count": len(without),
                "detail": None,
                "media_id": without[0]["media_id"],
                "comments": without[0]["comments"],
            }
        )

    tracking_opens = (
        db.query(IgAutomationEvent.id)
        .filter(IgAutomationEvent.tenant_id == tenant_id, IgAutomationEvent.kind == "opened")
        .first()
        is not None
    )
    funnel = [
        {"key": "triggered", "label": "Comments and messages matched", "value": cur["triggered"]},
        {"key": "dms_sent", "label": "DMs sent", "value": cur["dms_sent"]},
        {"key": "opened", "label": "Opened", "value": cur["opened"]},
        {"key": "forms_started", "label": "Started the questions", "value": cur["forms_started"]},
        {"key": "leads", "label": "Became a lead", "value": cur["leads"]},
        {"key": "bookings", "label": "Booked", "value": cur["bookings"]},
    ]
    return {
        "period": period,
        "from": f.isoformat(),
        "to": t.isoformat(),
        "previous": {"from": pf.isoformat(), "to": pt.isoformat()},
        "money_restricted": not money,
        "opens_tracked": tracking_opens,
        "kpis": cur,
        "previous_kpis": prev,
        "funnel": funnel,
        "top_posts": top[:10],
        "posts_without_automation": without,
        "alerts": alerts,
    }
