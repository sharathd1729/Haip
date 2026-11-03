"""More AI Executive detector rules (E2 sales + front desk, E3 marketing, social, ads, website, partnerships, platform).
Same contract as detectors.py: deterministic, reads only a shared source or the record itself, returns hits."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from app.services.chief.detectors import Ctx, _hit

# ── Ads analyst ────────────────────────────────────────────────────────────────────────────────────────────────


def ads_token_expiring(ctx: Ctx) -> list[dict]:
    """MK3: a connected integration's Meta token ends within 14 days (integration_health.token_days_left)."""
    from app.models.integration import Integration
    from app.services import integration_health

    out = []
    for row in ctx.db.query(Integration).filter(Integration.tenant_id == ctx.tid, Integration.status == "active").all():
        left = integration_health.token_days_left(row.config, ctx.now)
        if left is None or left > 14:
            continue
        kind = getattr(row.kind, "value", row.kind)
        label = integration_health.label(kind)
        text = f"The {label} access token has ended." if left <= 0 else f"The {label} access token ends in {left} days."
        out.append(
            _hit(
                "critical" if left <= 3 else "high",
                f"{label} token {'has ended' if left <= 0 else 'ends soon'}",
                text + " Replace it with a never-expiring System User token.",
                {"days_left": left},
                [{"type": "integration", "id": row.id}],
                target_id=row.id,
                cta_label="Open integrations",
                cta_href="/dashboard/settings/integrations",
            )
        )
    return out


def ads_attribution_gap(ctx: Ctx) -> list[dict]:
    """MK5: Meta reports >= 20 chats from ads in 7 days but HAIP traced < 20% of them (meta_ads_service.summary). Usually the
    Meta app is not subscribed to ``messaging_referral``."""
    from app.services import meta_ads_service

    row = meta_ads_service.get_row(ctx.db, ctx.tid)
    if row is None or (row.config or {}).get("ad_account_id") is None:
        return []
    t = meta_ads_service.summary(ctx.db, ctx.tid, days=7)["totals"]
    meta, haip = int(t.get("meta_conversations") or 0), int(t.get("haip_conversations") or 0)
    if meta < 20 or haip / meta >= 0.2:
        return []
    pct = round(haip * 100 / meta)
    return [
        _hit(
            "medium",
            "Most ad chats are not traced to their ad",
            f"Meta counted {meta} chats from ads in 7 days; HAIP "
            f"traced {haip} ({pct}%). Check that the Meta app is subscribed to messaging_referral.",
            {"meta_chats": meta, "traced": haip, "traced_pct": pct},
            [],
            cta_label="Open Marketing",
            cta_href="/dashboard/marketing",
        )
    ]


# ── Data analyst (owner metrics) ───────────────────────────────────────────────────────────────────────────────


def _week_vs_month(ctx: Ctx):
    from app.services.date_presets import IST

    end_day = ctx.today() - timedelta(days=1)
    lo = lambda d: datetime.combine(d, time.min, tzinfo=IST).astimezone(UTC)  # noqa: E731
    hi = lambda d: datetime.combine(d, time.max, tzinfo=IST).astimezone(UTC)  # noqa: E731
    return (lo(end_day - timedelta(days=6)), hi(end_day)), (
        lo(end_day - timedelta(days=34)),
        hi(end_day - timedelta(days=7)),
    )


def _drop_hit(code_word: str, cur: int, prev: int, title: str, href: str) -> list[dict]:
    from app.services.analyst import stats

    res = stats.compare_counts(prev, cur, prev_days=28, cur_days=7)
    if res["verdict"] != "down":
        return []
    expected = round(res["expected"])
    return [
        _hit(
            "medium",
            title,
            f"{cur} {code_word} in the last 7 days against about {expected} expected from the 4 weeks "
            "before (a real drop, not chance).",
            {"last_7_days": cur, "expected": expected, "previous_28_days": prev},
            [],
            cta_label="Open the analyst",
            cta_href=href,
        )
    ]


def owner_leads_down(ctx: Ctx) -> list[dict]:
    """OW3: new leads (lead_metrics.count_new_leads) in the last 7 days significantly below the 28 days before."""
    from app.services import lead_metrics

    (c_lo, c_hi), (p_lo, p_hi) = _week_vs_month(ctx)
    cur = lead_metrics.count_new_leads(ctx.db, ctx.tid, c_lo, c_hi)
    prev = lead_metrics.count_new_leads(ctx.db, ctx.tid, p_lo, p_hi)
    return _drop_hit("new leads", cur, prev, "New leads are down this week", "/dashboard/analyst")


def owner_bookings_down(ctx: Ctx) -> list[dict]:
    """OW3b: bookings made (kpi_metrics.booked_totals) in the last 7 days significantly below the 28 days before."""
    from app.services import kpi_metrics

    (c_lo, c_hi), (p_lo, p_hi) = _week_vs_month(ctx)
    cur, _ = kpi_metrics.booked_totals(ctx.db, ctx.tid, c_lo, c_hi)
    prev, _ = kpi_metrics.booked_totals(ctx.db, ctx.tid, p_lo, p_hi)
    return _drop_hit("bookings", cur, prev, "Bookings are down this week", "/dashboard/analyst")


# ── E2 detectors (each has a plan in plans.py) ─────────────────────────────────────────────────────────────────


def sales_autopilot_ignored(ctx: Ctx) -> list[dict]:
    """SA9: >= 15 lead-stage suggestions older than 3 days nobody applied, while the lead autopilot is in "suggest"."""
    from sqlalchemy import func

    from app.models.lead_autopilot import LeadAutopilotEvent
    from app.services import lead_autopilot_service

    if lead_autopilot_service.get_settings(ctx.db, ctx.tid).get("mode") != "suggest":
        return []
    n = int(
        ctx.db.query(func.count(LeadAutopilotEvent.id))
        .filter(
            LeadAutopilotEvent.tenant_id == ctx.tid,
            LeadAutopilotEvent.status == "suggested",
            LeadAutopilotEvent.created_at <= ctx.now - timedelta(days=3),
        )
        .scalar()
        or 0
    )
    if n < 15:
        return []
    return [
        _hit(
            "medium",
            f"{n} lead-stage suggestions nobody applied",
            f"The lead autopilot suggested {n} stage moves more than 3 days ago and nobody applied them, so the pipeline "
            "is out of date.",
            {"suggestions": n},
            [],
            cta_label="Lead autopilot settings",
            cta_href="/dashboard/settings/lead-autopilot",
        )
    ]


CLUSTER_SIMILARITY = 0.5  # agent_escalation_rules.similar: the same bar its repeat-question trigger uses


def concierge_repeat_questions(ctx: Ctx) -> list[dict]:
    """CO1: the same guest question went to a manager >= 3 times in 14 days and the team answered it, with nothing saved
    to the knowledge base yet. One finding per question (target = the earliest consult in the group)."""
    from app.models.agent_consult import AgentConsult
    from app.models.knowledge import KnowledgeEntry
    from app.services.agent_escalation_rules import similar

    rows = (
        ctx.db.query(AgentConsult)
        .filter(
            AgentConsult.tenant_id == ctx.tid,
            AgentConsult.status == "answered",
            AgentConsult.answered_at >= ctx.now - timedelta(days=14),
        )
        .order_by(AgentConsult.answered_at.asc())
        .limit(300)
        .all()
    )
    groups: list[list] = []
    for c in rows:
        home = next((g for g in groups if similar(c.question or "", g[0].question or "") >= CLUSTER_SIMILARITY), None)
        if home is None:
            groups.append([c])
        else:
            home.append(c)
    saved = {
        ref
        for (ref,) in ctx.db.query(KnowledgeEntry.source_ref).filter(
            KnowledgeEntry.tenant_id == ctx.tid, KnowledgeEntry.source_ref.like("consult:%")
        )
    }
    out = []
    for g in groups:
        if len(g) < 3 or any(c.saved_to_kb_entry_id or f"consult:{c.id}" in saved for c in g):
            continue
        out.append(
            _hit(
                "medium",
                f"The same guest question went to a manager {len(g)} times",
                f"Guests asked the same thing {len(g)} times in 14 days; each time the AI had to ask a manager. "
                "Saving the team's answer lets the AI reply itself.",
                {"asked": len(g)},
                [
                    {
                        "type": "consult",
                        "id": c.id,
                        "href": f"/dashboard/inbox?conversation={c.conversation_id}&consult={c.id}",
                    }
                    for c in g
                ],
                target_id=g[0].id,
                cta_label="Open the knowledge base",
                cta_href="/dashboard/settings/knowledge",
            )
        )
    return out
