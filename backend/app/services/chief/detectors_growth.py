"""AI Executive detectors, E3: marketing, social media, ads, website, partnerships and the public API.
Same contract as detectors.py: deterministic, reads only a shared source or the record itself, returns hits; ``numbers``
are the only figures an explanation may repeat and ``evidence`` is record ids, never names or phone numbers.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, time, timedelta

from app.services.chief.detectors import Ctx, _hit, _plural

COMMENT_SPIKE = 10  # comments on one post / ad in 24 h
AD_SPEND_NO_LEADS = 2000  # rupees on one campaign in 7 days with no traced lead
WEBHOOK_FAILURES = 10  # failed deliveries in a row (the endpoint switches itself off at 100)


def site_v2(ctx: Ctx):
    """The workspace's website when it is a v2 site that "Change something" can edit (website_change), else None."""
    from app.services import website_spec_service, website_version_service
    from app.services.website_service import get_site

    site = get_site(ctx.db, ctx.tid)
    if site is None:
        return None
    try:
        return site if website_spec_service.is_v2(website_version_service.head(ctx.db, site).doc) else None
    except Exception:  # noqa: BLE001 -- a site with no version yet
        return None


def social_comment_spike(ctx: Ctx) -> list[dict]:
    """MK1: >= 10 Instagram comments in 24 h on one post or ad (comment messages, process_instagram_comment) and no
    post-wide auto-reply rule for it (automation_rules ig_comment_received with that media_id)."""
    from app.models.automation import AutomationRule
    from app.models.conversation import ChannelType, Message, MessageDirection

    rows = (
        ctx.db.query(Message.channel_metadata)
        .filter(
            Message.tenant_id == ctx.tid,
            Message.channel == ChannelType.INSTAGRAM,
            Message.direction == MessageDirection.INBOUND,
            Message.created_at >= ctx.now - timedelta(hours=24),
        )
        .limit(5000)
        .all()
    )
    per_media = Counter(
        (m or {}).get("media_id") for (m,) in rows if (m or {}).get("source") == "comment" and (m or {}).get("media_id")
    )
    if not per_media:
        return []
    covered = {
        (r.trigger_config or {}).get("media_id")
        for r in ctx.db.query(AutomationRule).filter_by(
            tenant_id=ctx.tid, trigger="ig_comment_received", is_active=True
        )
    }
    return [
        _hit(
            "high",
            f"{n} comments on one post in a day, with no auto-reply",
            f"A post or ad got {n} comments in the last 24 hours and nothing answers them automatically. People who "
            "comment are asking; a quick DM turns them into chats.",
            {"comments": n},
            [{"type": "instagram_media", "id": media}],
            target_id=media,
            cta_label="Open the inbox",
            cta_href="/dashboard/inbox",
        )
        for media, n in per_media.most_common(5)
        if n >= ctx.level("MK1", COMMENT_SPIKE) and media not in covered
    ]


def marketing_cadence_drop(ctx: Ctx) -> list[dict]:
    """MK4: HAIP-published posts in the last 14 days are under half the 14 days before (>= 4 before), with Marketing
    Studio on (marketing_reports._published, the count its health score uses)."""
    from app.services import marketing_agency_run, marketing_reports

    if not marketing_agency_run.module_enabled(ctx.db, ctx.tid):
        return []
    today = ctx.today()
    cur = marketing_reports._published(ctx.db, ctx.tid, today - timedelta(days=13), today)
    prev = marketing_reports._published(ctx.db, ctx.tid, today - timedelta(days=27), today - timedelta(days=14))
    if prev < 4 or cur * 2 >= prev:
        return []
    return [
        _hit(
            "medium",
            "Posting has slowed down",
            f"{cur} posts in the last 14 days against {prev} in the 14 days before.",
            {"last_14_days": cur, "previous_14_days": prev},
            [],
            cta_label="Open Marketing Studio",
            cta_href="/dashboard/marketing/studio",
        )
    ]


def reviews_unanswered(ctx: Ctx) -> list[dict]:
    """MK7: Google reviews older than 3 days with no reply and no draft (marketing_guest_reviews)."""
    from app.models.marketing import MarketingGuestReview

    cutoff = (ctx.now - timedelta(days=3)).isoformat()
    rows = (
        ctx.db.query(MarketingGuestReview)
        .filter(
            MarketingGuestReview.tenant_id == ctx.tid,
            MarketingGuestReview.reply_status.in_(("none", "failed")),
            MarketingGuestReview.reviewed_at.isnot(None),
            MarketingGuestReview.reviewed_at <= cutoff,
        )
        .order_by(MarketingGuestReview.reviewed_at.asc())
        .limit(50)
        .all()
    )
    if not rows:
        return []
    low = sum(1 for r in rows if (r.rating or 5) <= 3)
    return [
        _hit(
            "high" if low else "medium",
            f"{_plural(len(rows), 'Google review')} with no reply",
            f"{_plural(len(rows), 'review')} older than 3 days have no reply ({low} of 3 stars or less). Replies are "
            "public and future guests read them.",
            {"reviews": len(rows), "low_rated": low},
            [{"type": "google_review", "id": r.id} for r in rows],
            cta_label="Reply to reviews",
            cta_href="/dashboard/marketing/studio",
        )
    ]


def ads_spend_no_leads(ctx: Ctx) -> list[dict]:
    """MK2: a Meta campaign spent >= Rs 2,000 in 7 days with no lead traced to it (meta_ads_service.summary). Ads are
    read-only in HAIP: a recommendation only; a person changes the campaign in Ads Manager."""
    from app.services import meta_ads_service

    row = meta_ads_service.get_row(ctx.db, ctx.tid)
    if row is None or (row.config or {}).get("ad_account_id") is None:
        return []
    out = []
    limit = ctx.level("MK2", AD_SPEND_NO_LEADS)
    for c in meta_ads_service.summary(ctx.db, ctx.tid, days=7)["campaigns"]:
        spend = float(c.get("spend") or 0)
        if spend < limit or c.get("haip_leads"):
            continue
        name = (c.get("campaign_name") or "A campaign")[:80]
        out.append(
            _hit(
                "high",
                f"{name}: money spent, no leads",
                f"{name} spent Rs {round(spend)} in 7 days and HAIP "
                "traced no lead to it. Check the ad's audience and message in Ads Manager, or pause it.",
                {"spend": round(spend), "leads": 0},
                [{"type": "ad_campaign", "id": c.get("campaign_id")}],
                target_id=c.get("campaign_id"),
                cta_label="Open Marketing",
                cta_href="/dashboard/marketing",
            )
        )
    return out


def _views(ctx: Ctx, a, b) -> int:
    from sqlalchemy import func

    from app.models.website import SitePageView

    return int(
        ctx.db.query(func.coalesce(func.sum(SitePageView.views), 0))
        .filter(SitePageView.tenant_id == ctx.tid, SitePageView.day >= a.isoformat(), SitePageView.day <= b.isoformat())
        .scalar()
        or 0
    )


def _website_enquiries(ctx: Ctx, a, b) -> int:
    from sqlalchemy import func

    from app.models.inquiry import Inquiry, InquirySource
    from app.services import kpi_metrics

    lo, hi = datetime.combine(a, time.min, tzinfo=UTC), datetime.combine(b, time.max, tzinfo=UTC)
    return int(
        ctx.db.query(func.count(Inquiry.id))
        .filter(*kpi_metrics.lead_filters(ctx.tid, lo, hi), Inquiry.source == InquirySource.WEBSITE)
        .scalar()
        or 0
    )


def website_traffic_not_converting(ctx: Ctx) -> list[dict]:
    """WB1: website visits in the last 7 days >= 200 and up >= 30% on the 7 before, while enquiries per 100 visits fell to
    60% or less of the week before (site_page_views + website enquiries by kpi_metrics.lead_filters)."""
    if site_v2(ctx) is None:
        return []
    today = ctx.today()
    cur_a, prev_a, end = today - timedelta(days=7), today - timedelta(days=14), today - timedelta(days=1)
    v_cur, v_prev = _views(ctx, cur_a, end), _views(ctx, prev_a, cur_a - timedelta(days=1))
    e_cur, e_prev = _website_enquiries(ctx, cur_a, end), _website_enquiries(ctx, prev_a, cur_a - timedelta(days=1))
    if v_cur < 200 or v_prev == 0 or v_cur < 1.3 * v_prev or e_prev == 0:
        return []
    if e_cur * v_prev > 0.6 * e_prev * v_cur:  # rate now > 60% of the rate before, without dividing
        return []
    return [
        _hit(
            "medium",
            "More website visits, fewer enquiries",
            f"Visits rose to {v_cur} from {v_prev} the week before, but enquiries were {e_cur} against {e_prev}.",
            {"visits": v_cur, "visits_before": v_prev, "enquiries": e_cur, "enquiries_before": e_prev},
            [],
            cta_label="Open the website",
            cta_href="/dashboard/marketing/website",
        )
    ]


def website_peak_weekend(ctx: Ctx) -> list[dict]:
    """WB3: a long weekend 21-45 days away with at least half its nights still free across the vehicles / villas
    (marketing_demand.long_weekends + free_nights), and a v2 website that can carry a short seasonal section."""
    from app.services import marketing_demand

    if site_v2(ctx) is None:
        return []
    today = ctx.today()
    state = marketing_demand.home_state(ctx.db, ctx.tenant)
    out = []
    for lw in marketing_demand.long_weekends(state, today + timedelta(days=21), today + timedelta(days=45))[:2]:
        a, b = datetime.fromisoformat(lw["start"]).date(), datetime.fromisoformat(lw["end"]).date()
        free = marketing_demand.free_nights(ctx.db, ctx.tid, a, b)
        nights = (b - a).days + 1
        if not free:
            continue
        free_count = sum(len(v) for v in free.values())
        if free_count * 2 < len(free) * nights:
            continue
        pct = round(free_count * 100 / (len(free) * nights))
        reason = (lw.get("reason") or "Long weekend")[:80]
        out.append(
            _hit(
                "medium",
                f"Long weekend from {lw['start']} is mostly free",
                f"{reason} ({lw['days']} days from {lw['start']}): {pct}% of nights are still free.",
                {"free_pct": pct, "days": lw["days"]},
                [{"type": "long_weekend", "id": lw["start"], "end": lw["end"], "label": reason}],
                target_id=lw["start"],
                cta_label="Open the website",
                cta_href="/dashboard/marketing/website",
            )
        )
    return out


def website_drafts_unpublished(ctx: Ctx) -> list[dict]:
    """WB5: trips / day plans saved as drafts never show on the website or to the AI (website_autobuild.drafts)."""
    from app.services import website_autobuild

    if site_v2(ctx) is None:
        return []
    rows = website_autobuild.drafts(ctx.db, ctx.tenant)
    if not rows:
        return []
    return [
        _hit(
            "low",
            f"{_plural(len(rows), 'trip')} in draft, not on the website",
            "These packages or day plans are saved as drafts, so the website and the AI cannot offer them.",
            {"drafts": len(rows)},
            [{"type": "business_record", "id": r["id"]} for r in rows],
            cta_label="Publish them",
            cta_href="/dashboard/marketing/website",
        )
    ]


def partnerships_unanswered(ctx: Ctx) -> list[dict]:
    """PA1: collaboration / barter requests whose "reply yes or no" task is open for more than a day (collab_requests)."""
    from app.models.task import Task
    from app.services.collab_requests import TASK_PREFIX

    rows = (
        ctx.db.query(Task)
        .filter(
            Task.tenant_id == ctx.tid,
            Task.is_done.is_(False),
            Task.title.ilike(TASK_PREFIX + "%"),
            Task.created_at <= ctx.now - timedelta(hours=24),
        )
        .limit(50)
        .all()
    )
    if not rows:
        return []
    return [
        _hit(
            "medium",
            f"{_plural(len(rows), 'collaboration request')} waiting for a yes or no",
            "Creators or partners "
            "asked to collaborate and nobody has answered for over a day; the AI does not reply to these.",
            {"waiting": len(rows)},
            [
                {
                    "type": "conversation",
                    "id": t.conversation_id,
                    "href": f"/dashboard/inbox?conversation={t.conversation_id}",
                }
                for t in rows
                if t.conversation_id
            ],
            cta_label="Open the inbox",
            cta_href="/dashboard/inbox",
        )
    ]


def api_webhooks_failing(ctx: Ctx) -> list[dict]:
    """API1: an active outbound webhook with >= 10 failed deliveries in a row (it switches itself off at 100)."""
    from app.models.webhook import WebhookEndpoint
    from app.services.webhook_service import DISABLE_AFTER_FAILURES

    rows = (
        ctx.db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.tenant_id == ctx.tid,
            WebhookEndpoint.is_active.is_(True),
            WebhookEndpoint.consecutive_failures >= ctx.level("API1", WEBHOOK_FAILURES),
        )
        .all()
    )
    return [
        _hit(
            "high",
            "A connected system is not receiving HAIP's updates",
            f"Deliveries to a webhook failed "
            f"{w.consecutive_failures} times in a row; it switches off by itself at {DISABLE_AFTER_FAILURES}.",
            {"failures": w.consecutive_failures, "limit": DISABLE_AFTER_FAILURES},
            [{"type": "webhook_endpoint", "id": w.id}],
            target_id=w.id,
            cta_label="Open developer settings",
            cta_href="/dashboard/settings/developers",
        )
        for w in rows
    ]
