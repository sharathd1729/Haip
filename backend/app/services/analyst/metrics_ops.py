"""The analyst's team, AI, demand and pricing numbers for one period (code only).

Reused, never re-stated: missed calls / answered / connected (call_status_service, lead_task_closer.connected), first-contact
speed per owner (workflow_report_service via metrics_funnel), the AI scorecard (ai_scorecard.build, its own 7/30-day window,
labelled), check-in coverage (checkin_coverage.build) and the published catalogue (business_data_service).

  team       per user: calls received / answered / missed not returned, outbound made / connected, median first contact
             minutes, follow-up tasks due in the period vs done on time, leads -> booked
  ai         ai_scorecard block (replies, consults by reason, held-back reasons)
  demand     routes the guests named (inquiries.route_mentioned), which of them match nothing published ("unavailable asks",
             e.g. Goa / Kerala), packages quoted, check-in weekends below the coverage target
  pricing    price objections (call + lead AI readings that name price / budget), discount asks (consult reasons), quotes
             created vs accepted and their median amount
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Optional

from sqlalchemy.orm import Session

from app.models.agent_consult import AgentConsult
from app.models.call import Call, CallDirection
from app.models.inquiry import Inquiry
from app.models.task import Task
from app.models.user import User

_PRICE_WORDS = re.compile(r"\b(price|pric(?:ey|ing)|budget|expensive|cost(?:ly)?|afford|cheaper|rate|discount)\b", re.I)
_WORD = re.compile(r"[a-z]+")
_STOP = {"the", "a", "to", "and", "or", "of", "for", "in", "trip", "route", "via", "from", "bengaluru", "bangalore", "with"}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    from app.services.kpi_metrics import as_datetime
    return as_datetime(dt) if dt is not None else None


def team(db: Session, tenant_id: str, lo: datetime, hi: datetime, workflow_agents: list[dict], agent_segment: list[dict]) -> list[dict]:
    from app.services import call_status_service as cs
    from app.services.lead_task_closer import connected
    rows: dict[Optional[str], dict] = defaultdict(lambda: {"calls_received": 0, "calls_answered": 0, "missed_not_returned": 0,
                                                          "outbound_made": 0, "outbound_connected": 0,
                                                          "followups_due": 0, "followups_on_time": 0})
    for c in db.query(Call).filter(Call.tenant_id == tenant_id, Call.created_at >= lo, Call.created_at <= hi).all():
        r = rows[c.agent_id]
        if c.direction == CallDirection.INBOUND:
            r["calls_received"] += 1
            if cs.is_missed_call(c):
                if not c.recovered_by_call_id and not c.callback_dismissed_at:
                    r["missed_not_returned"] += 1
            else:
                r["calls_answered"] += 1
        else:
            r["outbound_made"] += 1
            r["outbound_connected"] += 1 if connected(c) else 0
    for t in db.query(Task).filter(Task.tenant_id == tenant_id, Task.due_date.isnot(None), Task.due_date >= lo,
                                   Task.due_date <= hi, Task.inquiry_id.isnot(None)).all():
        r = rows[t.assigned_to]
        r["followups_due"] += 1
        if t.is_done and t.completed_at and _aware(t.completed_at) <= _aware(t.due_date) + timedelta(minutes=30):
            r["followups_on_time"] += 1
    speed = {a["agent_id"]: a for a in workflow_agents}
    booked = {(a["key"] if a["key"] != "unassigned" else None): a for a in agent_segment}
    ids = {k for k in (*rows, *speed, *booked) if k}
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == tenant_id, User.id.in_(list(ids))).all()) if ids else {}
    out = []
    for uid in set(rows) | set(speed) | set(booked):
        r = rows.get(uid) or rows[uid]
        out.append({"user_id": uid, "name": names.get(uid, "Unassigned") if uid else "Unassigned", **r,
                    "first_contact_minutes": (speed.get(uid) or {}).get("first_contact_minutes"),
                    "leads": (booked.get(uid) or {}).get("n", 0), "booked": (booked.get(uid) or {}).get("x", 0)})
    return sorted(out, key=lambda r: (r["user_id"] is None, -(r["leads"] + r["calls_received"])))


def ai(db: Session, tenant, hi: datetime, days: int) -> dict:
    from app.services import ai_scorecard
    sc = ai_scorecard.build(db, tenant, "30d" if days > 7 else "7d", now=hi)
    return {"window": sc["ai_replies"]["period"], "replies": {k: sc["ai_replies"][k] for k in
                                                          ("sent_alone", "approved_as_written", "edited", "rejected", "decided",
                                                           "no_edit_share")},
            "consults": {"opened": sc["consults"]["opened"], "expired": sc["consults"]["expired"],
                         "by_reason": sc["consults"]["by_reason"][:8]},
            "answer_minutes": {k: sc["answer_minutes"][k] for k in ("answered", "median", "p90", "inside_sla_share")},
            "held_back": sc["held_back"]["reasons"][:6]}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2}


def _published_words(db: Session, tenant_id: str) -> set[str]:
    from app.services import business_data_service as bds
    words: set[str] = set()
    for kind in ("destination", "package"):
        for rec in bds.list_effective(db, tenant_id, kind):
            try:
                words |= _tokens(bds.parse(rec).name) | _tokens(rec.key.replace("-", " "))
            except Exception:  # noqa: BLE001 -- a record that no longer parses is simply not a match
                continue
    return words


def demand(db: Session, tenant_id: str, lo: datetime, hi: datetime, today: date, package_rows: list[dict]) -> dict:
    asked = Counter()
    unavailable = Counter()
    published = _published_words(db, tenant_id)
    for (route,) in db.query(Inquiry.route_mentioned).filter(Inquiry.tenant_id == tenant_id, Inquiry.created_at >= lo,
                                                             Inquiry.created_at <= hi, Inquiry.route_mentioned.isnot(None)).all():
        label = " ".join((route or "").split())[:40].title()
        if not label:
            continue
        asked[label] += 1
        if published and not (_tokens(route) & published):
            unavailable[label] += 1
    custom_route_consults = sum(1 for (codes,) in db.query(AgentConsult.reason_codes).filter(
        AgentConsult.tenant_id == tenant_id, AgentConsult.created_at >= lo, AgentConsult.created_at <= hi).all()
        if "custom_route" in (codes or []))
    coverage = None
    try:
        from app.services import checkin_coverage
        cov = checkin_coverage.build(db, tenant_id, today, today + timedelta(days=56))
        weekends = [w for w in cov["weekends"] if not w["partial"]]
        coverage = {"target": cov["target"], "weekends": len(weekends),
                    "below_target": [{"friday": w["friday"], "valid": w["valid"]} for w in weekends if w["below_target"]][:8]}
    except Exception:  # noqa: BLE001 -- coverage is a nice-to-have; the report never fails on it
        coverage = None
    return {"routes_asked": [{"label": k, "count": n} for k, n in asked.most_common(10)],
            "unavailable_asks": [{"label": k, "count": n} for k, n in unavailable.most_common(8)],
            "custom_route_consults": custom_route_consults, "packages_quoted": package_rows[:8],
            "checkin_coverage": coverage, "published_catalogue": bool(published)}


def _objection_text(obj) -> str:
    if isinstance(obj, dict):
        return str(obj.get("objection") or obj.get("type") or "")
    return str(obj or "")


def pricing(db: Session, tenant_id: str, lo: datetime, hi: datetime, quote_block: dict, quote_amounts: list[float]) -> dict:
    call_obj, call_ids = 0, []
    for cid, insights in db.query(Call.id, Call.ai_insights).filter(Call.tenant_id == tenant_id, Call.created_at >= lo,
                                                                    Call.created_at <= hi, Call.ai_insights.isnot(None)).all():
        ins = insights if isinstance(insights, dict) else {}
        text = _objection_text(ins.get("blocking_objection")) + " " + str(ins.get("decline_reason") or "")
        if _PRICE_WORDS.search(text):
            call_obj += 1
            call_ids.append(cid)
    by_size: dict[str, int] = defaultdict(int)
    lead_obj, lead_ids = 0, []
    for iid, analysis, adults in db.query(Inquiry.id, Inquiry.ai_analysis, Inquiry.adults).filter(
            Inquiry.tenant_id == tenant_id, Inquiry.updated_at >= lo, Inquiry.updated_at <= hi, Inquiry.ai_analysis.isnot(None)).all():
        a = analysis if isinstance(analysis, dict) else {}
        if _PRICE_WORDS.search(_objection_text(a.get("blocking_objection"))):
            lead_obj += 1
            lead_ids.append(iid)
            n = int(adults or 0)
            by_size["unknown" if n <= 0 else ("1-2" if n <= 2 else "3-4" if n <= 4 else "5+")] += 1
    discount_asks = sum(1 for (codes,) in db.query(AgentConsult.reason_codes).filter(
        AgentConsult.tenant_id == tenant_id, AgentConsult.created_at >= lo, AgentConsult.created_at <= hi).all()
        if "discount_request" in (codes or []))
    return {"price_objections_calls": call_obj, "price_objections_leads": lead_obj,
            "price_objections_by_group_size": dict(by_size), "discount_asks": discount_asks,
            "quotes_created": quote_block["created"], "quotes_shared": quote_block["shared"],
            "quotes_accepted": quote_block["accepted"],
            "median_quote_amount": round(median(quote_amounts), 0) if quote_amounts else None,
            "_evidence": {"calls": call_ids[:20], "inquiries": lead_ids[:20]}}
