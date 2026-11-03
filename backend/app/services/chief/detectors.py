"""The AI Executive's detector rules (E1, read-only). Each rule is deterministic and reads ONLY a shared source:
the work queue, lead_metrics / kpi_metrics, lead_outcome_report, integration_health, meta_ads_service, ops_today_service,
booking_service, wa_automatic_analytics, or the domain table that is itself the record (consults, draft outcomes, iCal feeds,
bridge sessions). A rule returns a list of hits (empty = the condition is gone and the finding resolves itself).

A hit: {target_id, severity, title, body, numbers, evidence, cta_label, cta_href}. ``numbers`` are the only figures the AI
explanation may repeat; ``evidence`` is record ids (+ an in-app link), never a name or a phone number.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from sqlalchemy.orm import Session

MAX_EVIDENCE = 10
SERIOUS_CONSULT = {
    "complaint",
    "refund",
    "refund_billing",
    "safety",
    "legal",
    "frustrated",
    "review_threat",
    "wants_human",
}


class Ctx:
    """One detection pass for one workspace. Shared reads are computed once per pass."""

    def __init__(self, db: Session, tenant, now: datetime | None = None):
        self.db, self.tenant = db, tenant
        self.now = now or datetime.now(UTC)
        self._queue: dict | None = None
        self._today = None

    @property
    def tid(self) -> str:
        return self.tenant.id

    def queue(self) -> dict:
        if self._queue is None:
            from app.services import work_queue_service

            self._queue = work_queue_service.build(self.db, self.tenant, None)
        return self._queue

    def today(self):
        if self._today is None:
            from app.services import booking_agenda_service

            self._today = booking_agenda_service.tenant_today(self.db, self.tid)
        return self._today


def _hit(
    severity: str,
    title: str,
    body: str,
    numbers: dict,
    evidence: list,
    *,
    target_id: str | None = None,
    cta_label: str | None = None,
    cta_href: str | None = None,
) -> dict:
    return {
        "target_id": target_id,
        "severity": severity,
        "title": title[:255],
        "body": body,
        "numbers": numbers,
        "evidence": evidence[:MAX_EVIDENCE],
        "cta_label": cta_label,
        "cta_href": cta_href,
    }


def _lead(item: dict) -> dict:
    iid = item.get("inquiry_id")
    return (
        {"type": "inquiry", "id": iid, "href": f"/dashboard/leads/{iid}"}
        if iid
        else {"type": "guest", "id": item.get("guest_id"), "href": item.get("href")}
    )


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


# ── Sales manager ──────────────────────────────────────────────────────────────────────────────────────────────


def sales_unattended(ctx: Ctx) -> list[dict]:
    """SA1: people waiting past the reply target (work queue severity urgent/critical on new_lead/reply), with what is
    missing to alert the team on WhatsApp (playbooks P3/P4, the Meta-approved alert template, staff who opted in)."""
    late = [
        i
        for i in ctx.queue()["items"]
        if i["kind"] in ("new_lead", "reply") and i["severity"] in ("urgent", "critical")
    ]
    if len(late) < 3:
        return []
    from app.services import lead_alert_service, lead_playbook_settings, wa_lead_pack
    from app.services.lead_playbook_catalog import NEW_LEAD_ALERT, SLA_ESCALATION

    critical = sum(1 for i in late if i["severity"] == "critical")
    alerts_on = (
        lead_playbook_settings.playbook(ctx.tenant, NEW_LEAD_ALERT)["active"]
        or lead_playbook_settings.playbook(ctx.tenant, SLA_ESCALATION)["active"]
    )
    template = wa_lead_pack.status_of(ctx.db, ctx.tid, wa_lead_pack.STAFF_ALERT)
    opted_in = sum(1 for r in lead_alert_service.recipients_view(ctx.db, ctx.tid) if r["whatsapp_opt_in"])
    gaps = []
    if not alerts_on:
        gaps.append("Team alerts for new leads are switched off.")
    if template != "APPROVED":
        gaps.append("The team alert WhatsApp template is not approved by Meta yet.")
    if not opted_in:
        gaps.append("Nobody on the team has turned on WhatsApp alerts.")
    body = (
        f"{_plural(len(late), 'person has', 'people have')} waited past the reply target ({critical} critical). "
        + " ".join(gaps)
    )
    return [
        _hit(
            "critical" if critical else "high",
            f"{_plural(len(late), 'lead')} waiting past the reply target",
            body.strip(),
            {"waiting": len(late), "critical": critical, "staff_opted_in": opted_in},
            [_lead(i) for i in late],
            cta_label="Open My day",
            cta_href="/dashboard/my-day",
        )
    ]


def sales_unowned(ctx: Ctx) -> list[dict]:
    """SA2: people on the queue that nobody owns (work_queue_service.unowned), not yet gone cold."""
    rows = [i for i in ctx.queue()["items"] if i.get("unowned") and i["severity"] != "stale"]
    if len(rows) < 5:
        return []
    return [
        _hit(
            "medium",
            f"{_plural(len(rows), 'lead')} nobody owns",
            "Nobody has taken these leads yet, so no one is chasing them.",
            {"unowned": len(rows)},
            [_lead(i) for i in rows],
            cta_label="Take them on My day",
            cta_href="/dashboard/my-day",
        )
    ]


def sales_at_risk(ctx: Ctx) -> list[dict]:
    """SA8: warm leads travelling within 30 days and quiet for 48 h (the queue's ``at_risk`` flag)."""
    rows = [i for i in ctx.queue()["items"] if "at_risk" in (i.get("flags") or [])]
    if len(rows) < 3:
        return []
    return [
        _hit(
            "medium",
            f"{_plural(len(rows), 'promising lead')} at risk",
            "Warm leads travelling in the next 30 days have been quiet for two days.",
            {"at_risk": len(rows)},
            [_lead(i) for i in rows],
            cta_label="Open My day",
            cta_href="/dashboard/my-day?flag=at_risk",
        )
    ]


def _top_lost(rep: dict) -> tuple[int, dict | None]:
    lost = rep.get("lost") or {}
    decided = int(lost.get("confirmed", 0)) + int(lost.get("proposed", 0))
    top = (lost.get("reasons") or [None])[0]
    return decided, top


def sales_lost_cluster(ctx: Ctx) -> list[dict]:
    """SA6: one lost reason is >= 35% of >= 10 decided lost leads in the last 30 days, and its share went up vs the 30 before
    (lead_outcome_report, confirmed + AI-proposed reasons)."""
    from app.services import lead_outcome_report

    today = ctx.today()
    cur = lead_outcome_report.build(ctx.db, ctx.tid, today - timedelta(days=30), today - timedelta(days=1))
    prev = lead_outcome_report.build(ctx.db, ctx.tid, today - timedelta(days=60), today - timedelta(days=31))
    decided, top = _top_lost(cur)
    if decided < 10 or not top:
        return []
    count = top["confirmed"] + top["proposed"]
    share = count / decided
    p_decided, _ = _top_lost(prev)
    p_row = next((r for r in (prev.get("lost") or {}).get("reasons", []) if r["reason"] == top["reason"]), None)
    p_share = (p_row["confirmed"] + p_row["proposed"]) / p_decided if p_row and p_decided >= 10 else None
    if share < 0.35 or (p_share is not None and share <= p_share):
        return []
    pct = round(share * 100)
    return [
        _hit(
            "medium",
            f"Most lost leads give one reason: {top['label']}",
            f"{count} of {decided} lost leads in the last 30 days ({pct}%) were lost for {top['label'].lower()}.",
            {"lost": decided, "reason_count": count, "share_pct": pct},
            [],
            target_id=top["reason"],
            cta_label="Why we win and lose",
            cta_href="/dashboard/reports",
        )
    ]


# ── Front desk ─────────────────────────────────────────────────────────────────────────────────────────────────


def concierge_consults_waiting(ctx: Ctx) -> list[dict]:
    """CO5: guest questions waiting for a manager past their answer time (agent_consults); a complaint, refund, safety or
    "wants a person" reason makes it critical."""
    from app.models.agent_consult import AgentConsult

    rows = (
        ctx.db.query(AgentConsult)
        .filter(AgentConsult.tenant_id == ctx.tid, AgentConsult.status == "open", AgentConsult.sla_due_at < ctx.now)
        .order_by(AgentConsult.sla_due_at.asc())
        .limit(200)
        .all()
    )
    if not rows:
        return []
    serious = [c for c in rows if SERIOUS_CONSULT & set(c.reason_codes or [])]
    body = f"{_plural(len(rows), 'guest question')} waiting past the answer time"
    body += f", {len(serious)} about a complaint, refund, safety or a guest asking for a person." if serious else "."
    ev = [
        {"type": "consult", "id": c.id, "href": f"/dashboard/inbox?conversation={c.conversation_id}&consult={c.id}"}
        for c in (serious + [c for c in rows if c not in serious])
    ]
    return [
        _hit(
            "critical" if serious else "high",
            f"{_plural(len(rows), 'guest question')} waiting for a manager",
            body,
            {"waiting": len(rows), "serious": len(serious)},
            ev,
            cta_label="Answer on My day",
            cta_href="/dashboard/my-day",
        )
    ]


def concierge_drafts_expired(ctx: Ctx) -> list[dict]:
    """CO2: >= 10 AI drafts expired unread in 24 h (ai_draft_outcomes outcome ``expired``): guests got no reply from them."""
    from sqlalchemy import func

    from app.models.ai_draft_outcome import AIDraftOutcome

    n = int(
        ctx.db.query(func.count(AIDraftOutcome.id))
        .filter(
            AIDraftOutcome.tenant_id == ctx.tid,
            AIDraftOutcome.outcome == "expired",
            AIDraftOutcome.created_at >= ctx.now - timedelta(hours=24),
        )
        .scalar()
        or 0
    )
    if n < 10:
        return []
    return [
        _hit(
            "high",
            f"{n} AI replies expired unread today",
            f"{n} replies the AI wrote in the last 24 hours expired before anyone approved them.",
            {"expired": n},
            [],
            cta_label="Open the inbox",
            cta_href="/dashboard/inbox",
        )
    ]


def concierge_bridge_down(ctx: Ctx) -> list[dict]:
    """CO4: a linked personal WhatsApp (it had a phone number) is disconnected or logged out for more than 15 minutes."""
    from app.models.whatsapp_personal_session import WhatsAppPersonalSession
    from app.models.whatsapp_personal_session import WhatsAppPersonalSessionStatus as S

    rows = (
        ctx.db.query(WhatsAppPersonalSession)
        .filter(
            WhatsAppPersonalSession.tenant_id == ctx.tid,
            WhatsAppPersonalSession.phone_number.isnot(None),
            WhatsAppPersonalSession.status.in_([S.DISCONNECTED, S.LOGGED_OUT]),
        )
        .all()
    )
    out = []
    for s in rows:
        since = s.updated_at if s.updated_at and s.updated_at.tzinfo else (s.updated_at or ctx.now).replace(tzinfo=UTC)
        minutes = int((ctx.now - since).total_seconds() // 60)
        if minutes < 15:
            continue
        out.append(
            _hit(
                "high",
                "Personal WhatsApp disconnected",
                f"A team member's personal WhatsApp has been disconnected "
                f"for {minutes} minutes, so its chats are not reaching HAIP.",
                {"minutes": minutes},
                [{"type": "whatsapp_personal_session", "id": s.id}],
                target_id=s.id,
                cta_label="Link it again",
                cta_href="/dashboard/settings/whatsapp-personal",
            )
        )
    return out


# ── Operations and payments ────────────────────────────────────────────────────────────────────────────────────


def ops_red_needs(ctx: Ctx) -> list[dict]:
    """OP2: red items on Ops today (ops_today_service: trip/stay files, fleet papers, defects, failed crew messages)."""
    from app.services.ops_pack_catalog import pack_for_business_type

    if pack_for_business_type(ctx.tenant.business_type) is None:
        return []
    from app.services import ops_today_service

    needs = ops_today_service.build(ctx.db, ctx.tid, now=ctx.now)["needs"]
    red = [n for n in needs if n["level"] == "red"]
    if not red:
        return []
    amber = sum(1 for n in needs if n["level"] == "amber")
    ev = [
        {"type": "ops_file", "id": n["file_id"], "href": f"/dashboard/ops/files/{n['file_id']}"}
        for n in red
        if n.get("file_id")
    ]
    return [
        _hit(
            "high",
            f"{_plural(len(red), 'urgent ops item')} on Ops today",
            f"{_plural(len(red), 'item')} on Ops today need someone now ({amber} more to watch).",
            {"red": len(red), "amber": amber},
            ev,
            cta_label="Open Ops today",
            cta_href="/dashboard/ops",
        )
    ]


def finance_arrivals_owing(ctx: Ctx) -> list[dict]:
    """OP1: confirmed bookings checking in tomorrow with money still owed (booking_service.financials_for)."""
    from app.models.property import Stay
    from app.services import booking_service

    tomorrow = ctx.today() + timedelta(days=1)
    stays = (
        ctx.db.query(Stay)
        .filter(Stay.tenant_id == ctx.tid, Stay.check_in == tomorrow, Stay.status == "confirmed")
        .all()
    )
    fin = booking_service.financials_for(ctx.db, ctx.tid, stays)
    owing = [s for s in stays if fin[s.id]["outstanding"] > 0]
    if not owing:
        return []
    return [
        _hit(
            "high",
            f"{_plural(len(owing), 'arrival')} tomorrow still owe money",
            f"{_plural(len(owing), 'booking')} checking in tomorrow still have a balance to pay.",
            {"bookings": len(owing)},
            [{"type": "stay", "id": s.id, "href": f"/dashboard/bookings/{s.id}"} for s in owing],
            cta_label="Open bookings",
            cta_href="/dashboard/bookings",
        )
    ]


# ── IT / integrations ──────────────────────────────────────────────────────────────────────────────────────────


def it_ical_failing(ctx: Ctx) -> list[dict]:
    """TE4: an active calendar import whose last fetch failed."""
    from app.models.ical_feed import ICalFeed

    rows = (
        ctx.db.query(ICalFeed)
        .filter(ICalFeed.tenant_id == ctx.tid, ICalFeed.is_active.is_(True), ICalFeed.last_status == "error")
        .all()
    )
    if not rows:
        return []
    names = ", ".join(sorted({f.name for f in rows}))[:120]
    return [
        _hit(
            "medium",
            f"{_plural(len(rows), 'calendar import')} failing",
            f"The last fetch failed for: {names}. Dates from those calendars are not being blocked.",
            {"feeds": len(rows)},
            [{"type": "ical_feed", "id": f.id} for f in rows],
            cta_label="Open calendar links",
            cta_href="/dashboard/settings/calendar-sync",
        )
    ]


def it_auto_messages_failing(ctx: Ctx) -> list[dict]:
    """TE6: >= 20% of >= 10 automatic guest messages failed in 24 h (wa_automatic_analytics, Meta delivery receipts)."""
    from app.services import wa_automatic_analytics

    t = wa_automatic_analytics.guest_messages(ctx.db, ctx.tid, ctx.now - timedelta(hours=24), ctx.now)["totals"]
    sent, failed = int(t.get("sent") or 0), int(t.get("failed") or 0)
    if sent + failed < 10 or failed / (sent + failed) < 0.2:
        return []
    pct = round(failed * 100 / (sent + failed))
    return [
        _hit(
            "high",
            f"{pct}% of automatic WhatsApp messages failed",
            f"{failed} of {sent + failed} automatic guest messages in the last 24 hours did not go through.",
            {"failed": failed, "total": sent + failed, "failed_pct": pct},
            [],
            cta_label="See what failed",
            cta_href="/dashboard/workflows",
        )
    ]


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
